# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

import re
from typing import Optional
from odl_kernel.types import ProcessNode, WorkerMode
from odl.utils import parse_review_artifact

class NodeInspector:
    
    @staticmethod
    def get_recreation_source_ids(node: ProcessNode) -> list[str]:
        """
        自身の入力（inputs）に含まれる「過去の世代の自身の成果物」をすべて特定して返す。
        ネストされたループの場合、外側のループの過去分と、内側のループの過去分の双方が
        含まれる可能性があるため、リスト形式で返却する。

        Returns:
            list[str]: 特定された過去の成果物IDのリスト
                       (例: ["Doc#.../v1", "Doc#.../v2/v1"])
        """
        current_output_id = node.wiring.output
        if not current_output_id:
            return []

        found_source_ids = []
        inputs_set = set(node.wiring.inputs) # 高速化のためSet化

        # 1. パス内の全ての世代セグメント (/v{N}) を探す
        #    例: ".../v2/v3" -> matches=[v2, v3]
        matches = list(re.finditer(r'/v(\d+)(?:/|$)', current_output_id))

        if not matches:
            return []

        for match in matches:
            current_ver = int(match.group(1))
            
            # 初回(v1)のセグメントは過去を持たないのでスキップ
            if current_ver <= 1:
                continue

            # 2. 「1つ前の世代」のID候補を作成する
            #    注意: ネスト構造の場合、「その階層だけ戻る」パターンと「その階層で打ち切る」パターンがあり得る
            #    ログの例では外側ループは打ち切り(truncation)型、内側は維持型の傾向があるため、
            #    ここでは安全に「置換して打ち切ったID」を候補として生成する。

            # マッチしたセグメントの開始位置までのプレフィックス
            # 例: ".../v2/v3" で v3 にマッチ -> ".../v2"
            prefix = current_output_id[:match.start()]
            
            # 過去バージョン文字列 "/v{N-1}"
            prev_ver_str = f"/v{current_ver - 1}"
            
            # 候補A: ここでパスを打ち切るパターン (Truncated)
            # 例: ".../v2/v3" (外側v2マッチ) -> ".../v1"
            candidate_truncated = prefix + prev_ver_str
            
            # 候補B: パスの残りを維持するパターン (Preserved - 念のため)
            # 例: ".../v2/v3" (外側v2マッチ) -> ".../v1/v3"
            # ※ログのケースではAが外側ループ、Bに近い形が内側ループだが、
            #   内側ループは末尾マッチなので A == B となる。
            suffix = current_output_id[match.end():] # マッチ以降の文字列
            candidate_preserved = prefix + prev_ver_str + suffix

            # 3. 入力に含まれているかチェック
            if candidate_truncated in inputs_set:
                found_source_ids.append(candidate_truncated)
            
            # 候補AとBが異なる場合のみBもチェック
            if candidate_preserved != candidate_truncated and candidate_preserved in inputs_set:
                found_source_ids.append(candidate_preserved)

        # 重複を除去して返す (念のため)
        return sorted(list(set(found_source_ids)))

    @staticmethod
    def is_recreation_by_input(node: ProcessNode) -> bool:
        """
        [判定ロジック]
        自身の「過去の世代の成果物」が、1つ以上自身の入力に含まれているかを判定する。
        get_recreation_source_ids の結果リストが空でなければ True とする。
        """
        ids = NodeInspector.get_recreation_source_ids(node)
        return len(ids) > 0
    
    @staticmethod
    def is_recreation_source(node: ProcessNode, artifact_id: str) -> bool:
        """
        指定された artifact_id が、このノードにとっての「再生成元（過去の自分）」であるかを判定する。

        Logic:
            get_recreation_source_ids() で特定される「入力に含まれる正当な過去バージョンリスト」の中に、
            指定された artifact_id が存在するかを確認する。

        Args:
            node: 判定対象のProcessNode
            artifact_id: 判定したい成果物ID (例: "Doc#.../v1")

        Returns:
            bool: 再生成元であれば True
        """
        # 1. artifact_id が空なら即 False
        if not artifact_id:
            return False

        # 2. このノードにおける「正当な過去の自分リスト」を取得
        #    (パス計算、入力存在チェック済みのリスト)
        valid_sources = NodeInspector.get_recreation_source_ids(node)

        # 3. 含まれているか判定
        return artifact_id in valid_sources

    @staticmethod
    def is_validation_target(node: ProcessNode, artifact_id: str) -> bool:
        """
        指定された成果物IDが、このノードの「検証対象文書」であるかを判定する。

        Logic:
            1. ノードが 'validate' モードの Worker であるか確認する。
            2. ノードの出力ID (Output) がレビュー命名規則 ('Target__Review_Agent') に従っているか解析する。
            3. 出力IDから導出された 'Target' 名が、指定された artifact_id の論理名と一致するか確認する。
            4. 指定された artifact_id が、実際にノードの inputs に含まれているか確認する。

        Args:
            node: 判定対象のProcessNode
            artifact_id: 判定したい入力成果物のID (例: "ProjectDoc#j1/v1")

        Returns:
            bool: 検証対象であれば True
        """
        # 1. Mode Check
        # validateモード以外（generate等）は、特定の「検証対象」を持たない（またはInput全てが材料）
        if node.params.get("mode") != WorkerMode.VALIDATE:
            return False

        # 2. Output Analysis (Reverse Engineering)
        # Output ID: "ProjectDoc__Review_SecuritySpecialist#..."
        # ここから "ProjectDoc" を抽出する
        current_output = node.wiring.output
        if not current_output:
            return False
            
        # odl.utils.parse_review_artifact は (TargetName, AgentName) を返す
        # 戻り値例: ("ProjectDoc", "SecuritySpecialist")
        parsed = parse_review_artifact(current_output) #
        if not parsed:
            # 命名規則に従っていない場合（カスタムなvalidateノードなど）は判定不能としてFalse
            return False
        
        target_logical_name, _ = parsed

        # 3. Match Logical Name
        # artifact_id (例: "ProjectDoc#v1") が Target (例: "ProjectDoc") で始まっているか
        # 物理IDの区切り文字 '#' または文字列の完全一致を確認
        if not (artifact_id == target_logical_name or 
                artifact_id.startswith(f"{target_logical_name}#")):
            return False

        # 4. Wiring Check (Physical Presence)
        # 論理的に対象であっても、Wiring（入力）に含まれていなければ、このノードの処理対象ではない
        if artifact_id not in node.wiring.inputs:
            return False

        return True

# --- Helpers ---

def expected_prev_self_id_in_inputs(inputs, target_id):
    """
    inputsリストの中に target_id が含まれているか確認する。
    完全一致を基本とするが、要件によっては包含チェックでも良い。
    """
    return target_id in inputs