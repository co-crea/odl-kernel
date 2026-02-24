# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from enum import StrEnum

class InterventionIntent(StrEnum):
    """
    MANUAL_INTERVENTION における具体的な介入の意図。
    Cortex側で発生した操作に合わせて、Kernelが内部状態の整合やコマンド生成を行うためのヒント。
    
    Note: 
        'STOP' (停止予約) は存在しない。
        JobStatusが STOPPING に変更された状態で TICK が送られれば、
        Kernelは自動的に展開抑制（Global Suppression）と鎮火監視を行うため。
    """
    
    START = "START"
    """
    [起動通知]
    Context: Cortexにより JobStatus が CREATED -> RUNNING に変更された直後。
    Kernel Action: ルートノードが存在しない場合、Job.ir_root に基づき SPAWN コマンドを生成する。
    """

    RESUME = "RESUME"
    """
    [再開通知]
    Context: Cortexにより JobStatus が STOPPING/CANCELLED -> RUNNING に変更された直後。
    Kernel Action: 
        停止抑制を解除し、停止期間を取り戻すためのAnalyzeサイクルを回す。
        必要に応じて、中途半端なノードの再実行（巻き戻し）計画を立てる。
    """

    # --- 以下は Kernel が主導でステータス変更指示(TRANSITION)を出すもの ---

    RETRY = "RETRY"
    """
    [再試行 / 巻き戻し]
    Context: JobStatusは RUNNING のまま。特定のノードをやり直したい。
    Kernel Action: 
        指定されたノード(Failed等)を PENDING に巻き戻す TRANSITION コマンドを生成する。
    Payload: 
        - target_node_ids (List[str]): 巻き戻し対象のノードIDリスト
    """

    FORCE_RESULT = "FORCE_RESULT"
    """
    [強制完了 / スキップ]
    Context: JobStatusは RUNNING のまま。スタックしたノードを無理やり進めたい。
    Kernel Action: 
        指定されたノードを COMPLETED に遷移させ、結果を上書きする FINALIZE コマンドを生成する。
    Payload:
        - target_node_id (str): 対象ノード
        - result (BusinessResult): SUCCESS / REJECT 等
        - output_data (Any): 強制的に設定する出力データ
    """