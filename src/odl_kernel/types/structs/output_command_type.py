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

class CommandType(StrEnum):
    """
    KernelからHostへの指示（Output Signal）種別。
    
    各コマンドタイプに対応する `RuntimeCommand.payload` の期待構造は以下の通りです。
    Note: 状態の永続化データ自体は `AnalysisResult.updated_nodes` に含まれているため、
    Payloadは「イベントハンドリング」や「ログ出力」に必要な最小限の情報のみを持ちます。
    """

    TRANSITION = "TRANSITION"
    """
    [状態遷移通知]
    ノードのステータスが強制的に変更されたことを通知する。
    Hostはこれを見てログ出力や監視アラートを行うことができる。
    
    Context:
        - ControlノードのWake Up (PENDING -> RUNNING)
        - タイムアウト検知による強制失敗 (FAILED)
        - 子ノード失敗による親への波及 (Failure Propagation)
    
    Payload Structure:
        - from_status (LifecycleStatus): 変更前のステータス
        - to_status (LifecycleStatus): 変更後のステータス
        - reason (str, optional): 遷移の理由 (e.g., "E_EXECUTION_TIMEOUT")
    """

    FINALIZE = "FINALIZE"
    """
    [完了通知]
    ノードの処理が終了し、結果が確定したことを通知する。
    
    Context:
        - ノードが正常に完了 (COMPLETED)
    
    Payload Structure:
        - from_status (LifecycleStatus): 変更前のステータス
        - to_status (LifecycleStatus): COMPLETED 固定
        - result (BusinessResult): 確定した業務成果 (SUCCESS, REJECT, etc.)
    """

    SPAWN_CHILD = "SPAWN_CHILD"
    """
    [生成通知]
    新しい子ノードが生成されたことを通知する。
    実体レコードは `updated_nodes` に含まれているため、Hostは無条件に保存すればよい。
    
    Context:
        - Rootノードの生成 (Bootstrapping)
        - Controlノードによる展開 (Expansion)
    
    Payload Structure:
        - child_node_id (str): 生成された子のID
        - is_root (bool, optional): Root生成時のみ True
        - blueprint_selector (int, optional): デバッグ用 (何番目の定義か)
    """

    DISPATCH = "DISPATCH"
    """
    [実行指示]
    Action/Logicノードの処理を開始するために、外部または内部へのリクエストを要求する。
    **これは唯一、Hostが能動的な副作用（APIコール等）を行う必要があるコマンドである。**
    
    Context:
        - 新規生成されたActionノードの実行開始時
    
    Payload Structure:
        - worker_endpoint (str): 送信先識別子 ("WORKER_API" or "INTERNAL")
    """

    REQUIRE_DATA = "REQUIRE_DATA"
    """
    [データ要求]
    Logicノードが、計算に必要な外部データの取得・解決をHostに要求する。
    Kernelは純粋関数であり、外部リソースへのアクセス権を持たないため、このコマンドを通じて必要な情報を具体的に指定する。

    Context:
        - `iterator_init` ノードが RUNNING に遷移し、展開用データが必要になった時。
        - 将来的には、条件分岐のための外部パラメータ取得などにも使用される可能性がある。

    Payload Structure (Polymorphic):
        要求の種類(`request_type`)に応じて、必要な引数が異なる。

        1. Iterator Source Resolution:
           `iterator_init` がリスト展開のためのデータセットを要求する場合。
           
           - request_type (str): "RESOLVE_ITERATOR_SOURCE"
           - source (str): データの取得対象識別子 (e.g., "UserList", "DocA#v1")
           - item_key (str): データ内の各要素を一意に識別するためのキー名 (e.g., "user_id", "section_code")
             Hostはこのキーを使ってリストを正規化（Map化）して返すことが期待される。
             
        2. Scope Resolution (New for scope_resolve):
           「ブロック終了時に、内部で生成された動的履歴から『正』となる実体を決定する」ための要求。
           Hostは `context_vars` を使って親スコープを特定し、`strategy` に基づいて物理IDを選定する。
           
           - request_type (str): "RESOLVE_SCOPE" (固定)
           - target (str): 解決対象となる論理名 (e.g. "ProjectDoc")
           - from_scope (str): 解決元のスコープ種別 (e.g. "loop")
           - strategy (str): 解決戦略 (e.g. "take_latest_success")
           
           - context_vars (Dict[str, Any]): 
               現在のコンテキスト変数一覧。ネストされたループ情報を含む。
               Example: {"$LOOP": 2, "$LOOP^1": 1, "$KEY": "region_A"}
    """