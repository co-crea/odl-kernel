# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import List, Optional, Dict, Any
from datetime import datetime

from odl_kernel.types import (
    ProcessNode,
    RuntimeCommand,
    CommandType,
    LifecycleStatus,
    BusinessResult,
    OpCode,
    NodeType
)

class TransitionRules:
    """
    [Physics Logic] Transition Rules & Output Aggregation

    ノードの状態遷移、完了判定、および成果物集約を行う純粋関数ロジック。
    Analyzerの `Step A (Transition)` において呼び出され、ノードの次なる振る舞いを決定する。

    Physics Principles:
        1. Self-Driving (自律駆動):
           Control/Logicノードは、外部からの刺激がなくとも、自身の状態と子の状態に基づき自律的に遷移する。

        2. Data Dependency (データ依存):
           Logicノード（iterator_init, scope_resolve）は、計算に必要な外部データが
           自身のメモリ（output_aggregation）に存在しない場合、Hostに対してデータを要求し、解決を待機する。

        3. Fail Fast & Graceful Wait (異常系の制御):
           - Serial: エラー発生時は即座に停止する（Fail Fast）。
           - Parallel: 兄弟ノードの静止を待ってから停止する（Graceful Wait）。

        4. Last One Wins (結果採用):
           時系列構造（Serial/Loop）においては、最新（最後）の実行結果を親の成果物として採用する。
    """

    @staticmethod
    def evaluate(
        node: ProcessNode,
        children: List[ProcessNode],
        now: datetime
    ) -> Optional[RuntimeCommand]:
        """
        現在のノード状態と子ノード群に基づき、次に実行すべき状態遷移コマンドを導出する。

        Args:
            node: 評価対象のノード
            children: 生成済みの子ノードリスト
            now: 現在の物理時刻

        Returns:
            RuntimeCommand: 状態遷移や完了通知などの指示。何もしない場合はNone。
        """

        # =======================================================
        # 0. Wake Up (PENDING -> RUNNING)
        # =======================================================
        # Control/Logicノードは、生成直後(PENDING)はまず起動(RUNNING)しなければならない。
        # これにより、初期化処理や子ノード生成のサイクルを開始させる。
        if node.lifecycle_status == LifecycleStatus.PENDING:
            if node.node_type in (NodeType.CONTROL, NodeType.LOGIC):
                return RuntimeCommand(
                    type=CommandType.TRANSITION,
                    target_node_id=node.node_id,
                    payload={"to_status": LifecycleStatus.RUNNING}
                )
            return None

        # =======================================================
        # 1. Logic Node Execution (Async Data Request)
        # =======================================================
        if node.lifecycle_status == LifecycleStatus.RUNNING and node.node_type == NodeType.LOGIC:
            return TransitionRules._evaluate_logic_node(node)

        # =======================================================
        # 2. Zombie Killer (Timeout Detection)
        # =======================================================
        # 実行中のノードがタイムアウト時刻を超過した場合、強制的にFAILEDへ遷移させる。
        if node.lifecycle_status == LifecycleStatus.RUNNING:
            if node.timeout_at is not None and now.timestamp() > node.timeout_at:
                return RuntimeCommand(
                    type=CommandType.TRANSITION,
                    target_node_id=node.node_id,
                    payload={
                        "to_status": LifecycleStatus.FAILED,
                        "reason": "E_EXECUTION_TIMEOUT"
                    }
                )

        # =======================================================
        # 3. Control Node Evaluation (Propagation)
        # =======================================================
        # Controlノードは子ノードの状態を集約して自身の状態を決定する。
        if node.node_type == NodeType.CONTROL:
            return TransitionRules._evaluate_control_node(node, children)

        return None

    # -------------------------------------------------------------------------
    # Internal Logic Evaluation Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _evaluate_logic_node(node: ProcessNode) -> Optional[RuntimeCommand]:
        """Logicノード（iterator_init, scope_resolve）の実行判定"""

        # [Fix] 既にデータ要求済み（回答待ち）の場合は、何もしない（Noneを返す）
        # これにより、AnalyzerのFixed-point Iterationが収束する
        if node.runtime_context.system_variables.get("__waiting_for_data"):
            return None

        # A. Iterator Init (List Loading)
        if node.opcode == OpCode.ITERATOR_INIT:
            if not node.runtime_context.output_aggregation:
                return RuntimeCommand(
                    type=CommandType.REQUIRE_DATA,
                    target_node_id=node.node_id,
                    payload={
                        "request_type": "RESOLVE_ITERATOR_SOURCE",
                        "source": node.params.get("source"),
                        "item_key": node.params.get("item_key")
                    }
                )
            # データ解決済み -> 完了
            return RuntimeCommand(
                type=CommandType.FINALIZE,
                target_node_id=node.node_id,
                payload={
                    "result": BusinessResult.SUCCESS,
                    "output_data": node.runtime_context.output_aggregation[-1]
                }
            )

        # B. Scope Resolve (Reference Resolution)
        elif node.opcode == OpCode.SCOPE_RESOLVE:
            if not node.runtime_context.output_aggregation:
                return RuntimeCommand(
                    type=CommandType.REQUIRE_DATA,
                    target_node_id=node.node_id,
                    payload={
                        "request_type": "RESOLVE_SCOPE",
                        "target": node.params.get("target"),
                        "from_scope": node.params.get("from_scope"),
                        "strategy": node.params.get("strategy"),
                        "map_to": node.params.get("map_to"),
                        "context_vars": node.runtime_context.system_variables
                    }
                )
            # データ解決済み -> 完了
            resolved_id = node.runtime_context.output_aggregation[-1]
            return RuntimeCommand(
                type=CommandType.FINALIZE,
                target_node_id=node.node_id,
                payload={
                    "result": BusinessResult.SUCCESS,
                    "output_data": resolved_id
                }
            )

        # C. Other Logic Nodes
        return RuntimeCommand(
            type=CommandType.FINALIZE,
            target_node_id=node.node_id,
            payload={
                "result": BusinessResult.SUCCESS,
                "output_data": None
            }
        )

    @staticmethod
    def _evaluate_control_node(node: ProcessNode, children: List[ProcessNode]) -> Optional[RuntimeCommand]:
        """Controlノードの状態伝播判定"""

        failed_children = [c for c in children if c.lifecycle_status == LifecycleStatus.FAILED]
        running_children = [c for c in children if c.lifecycle_status in (LifecycleStatus.PENDING, LifecycleStatus.RUNNING)]
        completed_children = [c for c in children if c.lifecycle_status == LifecycleStatus.COMPLETED]

        is_all_settled = len(running_children) == 0

        # --- A. Failure Propagation (異常系) ---
        if failed_children:
            # Serial: 即時中断 (Fail Fast)
            # 子が1つでも死んだら親も即死する。後続は生成されない。
            if TransitionRules._is_serial_behavior(node.opcode):
                return RuntimeCommand(
                    type=CommandType.TRANSITION,
                    target_node_id=node.node_id,
                    payload={"to_status": LifecycleStatus.FAILED}
                )

            # Parallel: 全員の静止を待つ (Graceful Wait)
            # 他の兄弟が動いている間は親は死なない（待ち続ける）。
            if not is_all_settled:
                return None

            # 全員止まったので死亡確定
            return RuntimeCommand(
                type=CommandType.TRANSITION,
                target_node_id=node.node_id,
                payload={"to_status": LifecycleStatus.FAILED}
            )

        # --- B. Completion (正常系) ---
        # まだ動いている子がいれば待機
        if not is_all_settled:
            return None

        # 全ての子が完了していても、まだ生成すべき次世代（Expansion）が残っているか確認
        if TransitionRules._has_pending_expansion(node, children):
            return None

        # 全て完了し、生成予定もない -> 親自身の完了処理
        business_result = TransitionRules._aggregate_business_result(node.opcode, completed_children)
        output_data = TransitionRules._aggregate_output_data(node.opcode, completed_children)

        return RuntimeCommand(
            type=CommandType.FINALIZE,
            target_node_id=node.node_id,
            payload={
                "result": business_result,
                "output_data": output_data
            }
        )

    # -------------------------------------------------------------------------
    # Static Logic Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_serial_behavior(opcode: OpCode) -> bool:
        """Serial的な振る舞い（順序依存・Fail Fast）をするOpCodeか判定"""
        return opcode in (OpCode.SERIAL, OpCode.LOOP, OpCode.ITERATE)

    @staticmethod
    def _has_pending_expansion(node: ProcessNode, children: List[ProcessNode]) -> bool:
        """
        これ以上の子ノード生成（Expansion）が予定されているか判定する。
        Strategyの実装と整合性を保つ必要がある。
        """
        current_count = len(children)

        if node.opcode == OpCode.SERIAL:
            total_blueprints = len(node.children_blueprint)
            return current_count < total_blueprints

        if node.opcode == OpCode.LOOP:
            max_count = node.params.get("count", 1)
            # 上限に達していない場合は継続の可能性がある
            if current_count < max_count:
                # 直近の子供のビジネス結果によるbreak判定
                # (LoopExpansionStrategyと同様のロジック)
                if children:
                    last_child = children[-1]
                    break_on = node.params.get("break_on")
                    if break_on == "success" and last_child.business_result == BusinessResult.SUCCESS:
                        return False # 成功したので打ち切り（これ以上生成しない）
                return True # まだ続く
            return False # 上限到達

        if node.opcode == OpCode.ITERATE:
            strategy = node.params.get("strategy", "serial")
            if strategy == "parallel":
                # Parallelモードは一括生成なので、全員Settledなら生成待ちなし
                return False
            # Serialモードの場合、itemsの数だけ続く
            items = node.params.get("items", {})
            return current_count < len(items)

        if node.opcode == OpCode.PARALLEL:
            # Parallelは一括生成なので、全員Settledなら生成待ちなし
            return False

        return False

    @staticmethod
    def _aggregate_business_result(opcode: OpCode, children: List[ProcessNode]) -> BusinessResult:
        """
        子ノードの結果を集約して親のBusinessResultを決定する。
        """
        if not children:
            return BusinessResult.NONE

        # Serial/Loop: Last One Wins
        # 最後の子供の結果を採用する
        if TransitionRules._is_serial_behavior(opcode):
            return children[-1].business_result

        # Parallel: Result Aggregation
        # 全ての子の結果を見る
        results = set(c.business_result for c in children)

        # 優先度: REJECT > ERROR > SUCCESS > NONE
        if BusinessResult.REJECT in results:
            return BusinessResult.REJECT
        if BusinessResult.ERROR in results:
            return BusinessResult.ERROR
        if BusinessResult.SUCCESS in results:
            return BusinessResult.SUCCESS

        return BusinessResult.NONE

    @staticmethod
    def _aggregate_output_data(opcode: OpCode, children: List[ProcessNode]) -> Any:
        """
        子ノードの成果物(output_aggregation)を集約して親の成果物を決定する。
        """
        outputs = []
        for c in children:
            # 子が成果物を持っていればそれを採用、なければNone
            if c.runtime_context.output_aggregation:
                outputs.append(c.runtime_context.output_aggregation[-1])
            else:
                outputs.append(None)

        if not outputs:
            return None

        # Serial/Loop: Last One Wins
        if TransitionRules._is_serial_behavior(opcode):
            return outputs[-1]

        # Parallel: List Aggregation
        # 並列実行の結果はリストとしてまとめる
        return outputs