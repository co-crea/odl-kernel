# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import List

from odl_kernel.types import ProcessNode, LifecycleStatus, BusinessResult
from .base import ExpansionStrategy, ExpansionPlan


class LoopExpansionStrategy(ExpansionStrategy):
    """
    Loop Expansion Logic (Sequential & Dynamic Context)
    
    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic
    
    Responsibility:
        定義された単一のBlueprint (`contents`) を、指定回数 (`count`) または条件 (`break_on`) が満たされるまで、
        順次繰り返し展開する (Lazy Expansion)。
        直前のイテレーションの「システム状態」および「業務成果」を評価し、継続可否を厳密に判断する。
    
    Path Resolution (Strict Inheritance & Segmentation):
        Loopは階層構造に「仮想的な世代セグメント (v{N})」を物理的に挿入する。
        Blueprintの `stack_path` (例: .../v{$LOOP}/worker) は使用せず、
        「親パス」 + 「世代(v{N})」 + 「ノード名」 を結合して物理パスを構築する。
        
        Format: "{ParentPath}/v{Index}/{NodeName}"
    
    Context Injection:
        子ノードに対し、現在のイテレーション番号を示すシステム変数 `$LOOP` (1-based) を注入する。

    Exit Conditions (Critical):
        以下のいずれかに該当する場合、次のイテレーションは生成されず、ループ展開は終了（または中断）する：
        
        1. Count Limit: 指定回数 (`count`) に達した場合。
        2. System Failure: 直前のノードが `FAILED` (Timeout/Crash) した場合。
           -> システム的な継続性が失われたため、即時停止する。
        3. Business Error: 直前のノードが `BusinessResult.ERROR` を返した場合。
           -> 業務的な継続性が失われたため、即時停止する。
        4. Break Condition: `break_on="success"` 指定時に `SUCCESS` した場合。
    """

    def plan_next_nodes(
        self, 
        parent: ProcessNode, 
        current_children: List[ProcessNode]
    ) -> List[ExpansionPlan]:
        """
        Args:
            parent: 親ノード。paramsに 'count', 'break_on' 等を持つ。
            current_children: 生成済みのイテレーションノードリスト（生成順）。
        
        Returns:
            List[ExpansionPlan]: 次のイテレーションの生成計画。条件を満たさない場合は空リスト。
        """
        if not parent.children_blueprint:
            return []

        # LoopのBlueprintは常に1つ (contentsブロック)
        body_blueprint = parent.children_blueprint[0]
        
        # 現在の子供の数
        current_count = len(current_children)
        next_loop_var = current_count + 1 # 1-based indexing

        # 1. Parameter Validation & Limits
        max_count = parent.params.get("count", 1) # デフォルト1回
        if next_loop_var > max_count:
            return []

        # 2. Status Evaluation (System & Business)
        if current_count > 0:
            last_child = current_children[-1]
            
            # A. System Lifecycle Check (Fail Fast)
            # ノードが異常終了(FAILED)している場合、結果を待たずに即座にループを打ち切る。
            if last_child.lifecycle_status == LifecycleStatus.FAILED:
                return []
            
            # B. Sequential Wait
            # まだ実行中(RUNNING/PENDING)であれば、完了を待つ。
            if last_child.lifecycle_status != LifecycleStatus.COMPLETED:
                return []

            # C. Business Result Check
            # 正常完了(COMPLETED)した場合のみ、業務結果を評価する。
            result = last_child.business_result
            
            # Rule 1: Business ERROR は即停止
            if result == BusinessResult.ERROR:
                return []
            
            # Rule 2: break_on 判定
            break_on = parent.params.get("break_on")
            if break_on == "success":
                # 成功したらループを抜ける (Early Exit)
                if result == BusinessResult.SUCCESS:
                    return []
                # REJECT (否認) または NONE の場合は、成功を目指して継続する

        # 3. Path Resolution (Strict Segment Insertion)
        # Logic: ParentResolvedPath + "/v{N}" + "/" + NodeName
        node_name = self._get_node_name(body_blueprint)
        resolved_path = f"{parent.stack_path}/v{next_loop_var}/{node_name}"

        # 4. Create Plan
        return [ExpansionPlan(
            blueprint=body_blueprint,
            context_vars={"$LOOP": next_loop_var},
            resolved_path=resolved_path,
            original_index=0
        )]