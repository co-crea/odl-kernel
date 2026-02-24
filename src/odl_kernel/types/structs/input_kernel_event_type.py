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

class KernelEventType(StrEnum):
    """
    Analyzeをトリガーする事象（Input Event）の種類。
    
    各イベントタイプに対応する `KernelEvent.payload` の期待構造は以下の通りです。
    """

    TICK = "TICK"
    """
    [定期実行 / 状態確認]
    外部からの刺激ではなく、時間の経過や自律的な状態遷移を促進するために発行されるイベント。
    
    Context:
        - 定期実行ジョブ（Cron）
        - 停止中（STOPPING）ジョブの鎮火監視
        - `MANUAL_INTERVENTION` 後の状態整合性チェック
    
    Payload Structure:
        - (Empty)
    """

    ACTION_COMPLETED = "ACTION_COMPLETED"
    """
    [完了報告]
    WorkerやPersonaなどの外部エージェントが、割り当てられたタスク（Action Node）を
    正常に完了したことを通知するイベント。
    
    Context:
        - Worker APIへのコールバック受信時
        - 内部ロジック（Logic Node）の計算完了時
    
    Payload Structure:
        - result (BusinessResult): 業務的な成果判定 (SUCCESS, REJECT, ERROR, NONE)
        - output_data (Any): 生成された成果物データ（IDやオブジェクト）
    """

    ACTION_FAILED = "ACTION_FAILED"
    """
    [失敗報告]
    Workerがタスクの実行に失敗した（例外発生、システムエラー等）ことを通知するイベント。
    
    Context:
        - Workerからのエラー応答
        - タイムアウト検知（Host側での検知）
    
    Payload Structure:
        - reason (str): エラー理由やメッセージ
        - code (str, optional): エラーコード
    """

    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"
    """
    [手動介入]
    人間（オペレーター）の意思により、ジョブやノードの状態を強制的に操作するイベント。
    具体的な操作内容は `intervention_intent` フィールドで指定される。
    
    Context:
        - ジョブの開始（START）、一時停止、再開（RESUME）
        - 特定ノードの再試行（RETRY）や強制完了（FORCE_RESULT）
    
    Payload Structure:
        - (Dependent on `intervention_intent`)
        - RETRY -> { "target_node_ids": List[str] }
        - FORCE_RESULT -> { "result": ..., "output_data": ... }
    """

    DATA_RESOLVED = "DATA_RESOLVED"
    """
    [データ解決報告]
    `CommandType.REQUIRE_DATA` に対するHostからの応答イベント。
    Hostが外部リソースや内部履歴から特定・取得したデータをKernelに引き渡す。

    Context:
        - Hostがデータ要求を処理し、該当データの取得またはID特定に成功した後。

    Payload Structure (Polymorphic):
        要求元（Logic Node）の目的 (`request_type`) に応じて、解決データの形式が異なる。

        1. Iterator Source Resolution (for iterator_init):
           リスト展開のためのデータセット。
           - items (List[Dict]): 順序付きの要素リスト。
             Example: [{"key": "user_1", "value": "..."}, ...]

        2. Scope Resolution (for scope_resolve):
           動的履歴から特定された「正」となる物理ID。
           - resolved_id (str): 特定された物理ID。
             解決不能、または該当なしの場合は null (None) が設定される。
             Example: "ProjectDoc#j1-p1-d1/v2/worker_A"
    """