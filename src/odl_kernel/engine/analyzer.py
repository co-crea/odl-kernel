# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from typing import List, Dict, Any, Set, Optional
from odl.types import OpCode, NodeType, WiringObject

from odl_kernel.types import (
    JobSnapshot, KernelEvent, AnalysisResult,
    RuntimeCommand, CommandType, ProcessNode,
    LifecycleStatus, JobStatus, JobUpdate,
    ContextSchema, KernelEventType, BusinessResult
)
from .logic.node_id_generator import NodeIdGenerator
from .logic.transition_rules import TransitionRules
from .logic.variable_resolver import VariableResolver

# Strategies
from .logic.expansion.serial import SerialExpansionStrategy
from .logic.expansion.parallel import ParallelExpansionStrategy
from .logic.expansion.loop import LoopExpansionStrategy
from .logic.expansion.iterate import IterateExpansionStrategy


class OdlAnalyzer:
    """
    ODL実行の中核となる純粋関数エンジン (The Physics Engine)。

    [Architecture: Deep Analyze & Signal/State Separation]

    1. Deep Analyze (Fixed-point Iteration):
       本関数は、入力された状態に対し、物理的に進行可能な限界（Action待ち or 完全停止）まで
       内部でサイクルを回し続け、収束した結果を一括で返却する。
       これにより、Hostは「過渡状態」を意識することなく、常に安定した状態のみを観測できる。

    2. Signal (Command) vs State (UpdatedNodes):
       - updated_nodes: 状態の「真実（Truth）」。Hostはこれを無条件にDB保存する。
       - commands: 状態変化に伴う「シグナル」。Payloadは最小化され、分岐判断やログ通知に使用される。
    """

    # 無限ループ（物理崩壊）防止用の安全装置
    MAX_ITERATIONS = 100

    def analyze(self, snapshot: JobSnapshot, event: KernelEvent) -> AnalysisResult:
        """
        Main Entry Point: 物理法則に基づき、入力されたSnapshotとEventから次のアクションを導出する。
        """
        final_result = AnalysisResult()

        # Working Memory (Deep Copy)
        # 計算中の状態変更を即座に反映させるため、ミュータブルな辞書として展開する
        working_nodes: Dict[str, ProcessNode] = {
            k: v.model_copy(deep=True) for k, v in snapshot.nodes.items()
        }

        # -----------------------------------------------------------
        # 0. Global Suppression Check
        # -----------------------------------------------------------
        if snapshot.job.status == JobStatus.STOPPING:
            self._evaluate_suppression(snapshot, working_nodes, final_result)
            return final_result

        # -----------------------------------------------------------
        # 1. Root Bootstrapping (Initial Spawn)
        # -----------------------------------------------------------
        if not working_nodes and snapshot.job.status == JobStatus.RUNNING:
            self._bootstrap_root(snapshot, working_nodes, final_result)
            # Root生成も状態変化の一種なので、ここからメインループに入る

        # -----------------------------------------------------------
        # 2. Main Deep Loop (Fixed-point Iteration)
        # -----------------------------------------------------------
        # cocrea-2201: Pipelined Analyze (Step A -> B -> C)
        for _ in range(self.MAX_ITERATIONS):
            has_change = False

            # --- Step A: Transition (State Update) ---
            # 完了判定、タイムアウト、WakeUp(Pending->Running)などを処理
            active_nodes = [
                n for n in working_nodes.values()
                if n.lifecycle_status in (LifecycleStatus.PENDING, LifecycleStatus.RUNNING)
            ]
            for node in active_nodes:
                if self._step_a_transition(node, working_nodes, event, final_result):
                    has_change = True

            # --- Step B: Expansion (Structure Growth) ---
            # Controlノードによる子ノード生成
            control_nodes = [
                n for n in working_nodes.values()
                if n.node_type == NodeType.CONTROL
                and n.lifecycle_status == LifecycleStatus.RUNNING
            ]
            for node in control_nodes:
                if self._step_b_expansion(node, snapshot.job, working_nodes, final_result):
                    has_change = True

            # --- Step C: Dispatch (External Trigger) ---
            # 新規生成されたActionノードの実行開始
            pending_nodes = [
                n for n in working_nodes.values()
                if n.lifecycle_status == LifecycleStatus.PENDING
            ]
            for node in pending_nodes:
                if self._step_c_dispatch(node, working_nodes, final_result):
                    has_change = True

            # --- Convergence Check ---
            # 変化がなくなれば安定状態とみなして終了
            if not has_change:
                break

        # -----------------------------------------------------------
        # 3. Finalization
        # -----------------------------------------------------------
        self._evaluate_job_status(snapshot.job, working_nodes, final_result)

        # -----------------------------------------------------------
        # 4. Packaging (Unique Updates)
        # -----------------------------------------------------------
        # working_nodes は常に最新の状態を持っている。
        # final_result.updated_nodes に記録されたID（変更があったもの）について、
        # working_nodes から最新のオブジェクトを取り直して返却する。
        touched_ids = {n.node_id for n in final_result.updated_nodes}
        final_result.updated_nodes = [working_nodes[nid] for nid in touched_ids]

        return final_result

    # =========================================================================
    # Internal Steps
    # =========================================================================

    def _bootstrap_root(self, snapshot: JobSnapshot, nodes: Dict[str, ProcessNode], result: AnalysisResult):
        """Rootノードの初期生成"""
        ir = snapshot.job.ir_root
        id_gen = NodeIdGenerator(snapshot.job.job_id)
        node_id = id_gen.generate(ir.stack_path)

        # 1. State Update (Truth)
        root_node = self._simulate_spawn(
            node_id=node_id,
            blueprint=ir,
            resolved_path=ir.stack_path,
            context_vars={},
            parent_context=None
        )
        nodes[node_id] = root_node
        result.updated_nodes.append(root_node)

        # 2. Command (Signal)
        cmd = RuntimeCommand(
            type=CommandType.SPAWN_CHILD,
            target_node_id=snapshot.job.root_node_id or node_id,
            payload={
                "child_node_id": node_id,
                "is_root": True,
                "child_opcode": ir.opcode,
                "parent_opcode": None
            }
        )
        result.commands.append(cmd)

    def _step_a_transition(self, node: ProcessNode, nodes: Dict[str, ProcessNode], event: KernelEvent, result: AnalysisResult) -> bool:
        """Step A: 状態遷移ロジックの評価と適用"""

        # 1-A. External Event Handling (Action Completion)
        if event.type == KernelEventType.ACTION_COMPLETED and event.target_node_id == node.node_id:
            # ... (既存コード: ACTION_COMPLETED処理) ...
            if node.lifecycle_status == LifecycleStatus.COMPLETED:
                return False

            from_status = node.lifecycle_status

            node.lifecycle_status = LifecycleStatus.COMPLETED
            node.business_result = event.payload.get("result", BusinessResult.NONE)

            output_data = event.payload.get("output_data")
            if output_data:
                node.runtime_context.output_aggregation.append(output_data)

            result.updated_nodes.append(node)

            signal_cmd = RuntimeCommand(
                type=CommandType.FINALIZE,
                target_node_id=node.node_id,
                payload={
                    "from_status": from_status,
                    "to_status": LifecycleStatus.COMPLETED,
                    "result": node.business_result
                }
            )
            result.commands.append(signal_cmd)
            return True

        # 1-B. External Event Handling (Data Resolved) [UPDATED]
        if event.type == KernelEventType.DATA_RESOLVED and event.target_node_id == node.node_id:
            if node.lifecycle_status == LifecycleStatus.COMPLETED:
                return False

            # [Physics Fix] Idempotency Check
            if node.runtime_context.output_aggregation:
                pass 
            else:
                items = event.payload.get("items")
                resolved_id = event.payload.get("resolved_id")

                updated = False
                if items is not None:
                    node.runtime_context.output_aggregation.append(items)
                    updated = True
                elif resolved_id is not None:
                    node.runtime_context.output_aggregation.append(resolved_id)
                    updated = True

                if updated:
                    # [Fix] データ解決したので、待機フラグを下ろす
                    node.runtime_context.system_variables.pop("__waiting_for_data", None)
                    
                    result.updated_nodes.append(node)
                    return True

        # 2. Internal Rule Evaluation
        children = [nodes[cid] for cid in node.runtime_context.children_ids if cid in nodes]
        logic_cmd = TransitionRules.evaluate(node, children, event.occurred_at)

        if logic_cmd:
            from_status = node.lifecycle_status

            # State Update Application
            if logic_cmd.type == CommandType.TRANSITION:
                node.lifecycle_status = logic_cmd.payload["to_status"]
            elif logic_cmd.type == CommandType.FINALIZE:
                node.lifecycle_status = LifecycleStatus.COMPLETED
                node.business_result = logic_cmd.payload["result"]

            elif logic_cmd.type == CommandType.REQUIRE_DATA:
                # [Fix] 要求を出したので、待機フラグを立てる (State Mutation)
                # これにより、次回のEvaluateで二重発行が抑制され、ループが収束する
                node.runtime_context.system_variables["__waiting_for_data"] = True

            result.updated_nodes.append(node)

            # Signal
            signal_payload = {
                "from_status": from_status,
                "to_status": node.lifecycle_status
            }
            if logic_cmd.payload:
                signal_payload.update(logic_cmd.payload)

            signal_cmd = RuntimeCommand(
                type=logic_cmd.type,
                target_node_id=node.node_id,
                payload=signal_payload
            )
            result.commands.append(signal_cmd)
            return True

        return False

    def _step_b_expansion(self, node: ProcessNode, job, nodes: Dict[str, ProcessNode], result: AnalysisResult) -> bool:
        """Step B: 子ノードの展開ロジック"""
        strategy = self._select_strategy(node.opcode)
        if not strategy: return False

        children = [nodes[cid] for cid in node.runtime_context.children_ids if cid in nodes]
        plans = strategy.plan_next_nodes(node, children)
        if not plans: return False

        id_gen = NodeIdGenerator(job.job_id)
        has_spawn = False

        for plan in plans:
            new_id = id_gen.generate(plan.resolved_path)

            # 1. State Update (Truth)
            # Strategyの計画に加え、親のContextを継承・シフトさせて生成する
            # [Update] params_override を渡す
            new_node = self._simulate_spawn(
                node_id=new_id,
                blueprint=plan.blueprint,
                resolved_path=plan.resolved_path,
                context_vars=plan.context_vars,
                parent_context=node.runtime_context,
                params_override=plan.params_override  # <--- NEW
            )

            # Link Parent -> Child
            node.runtime_context.children_ids.append(new_id)
            nodes[new_id] = new_node

            result.updated_nodes.append(new_node)
            result.updated_nodes.append(node)

            # 2. Command (Signal)
            cmd = RuntimeCommand(
                type=CommandType.SPAWN_CHILD,
                target_node_id=node.node_id,
                payload={
                    "child_node_id": new_id,
                    "blueprint_selector": plan.original_index,
                    "parent_opcode": node.opcode,
                    "child_opcode": plan.blueprint.opcode
                }
            )
            result.commands.append(cmd)
            has_spawn = True

        return has_spawn

    def _step_c_dispatch(self, node: ProcessNode, nodes: Dict[str, ProcessNode], result: AnalysisResult) -> bool:
        """Step C: 実行指示ロジック"""
        # PENDING以外は無視
        if node.lifecycle_status != LifecycleStatus.PENDING:
            return False

        # Control/Logic Nodeは自己駆動するためDispatch対象外
        if node.node_type in (NodeType.CONTROL, NodeType.LOGIC):
            return False

        # 1. State Update (Truth)
        # DispatchされたノードはHost側で即座にRUNNINGにされる前提
        node.lifecycle_status = LifecycleStatus.RUNNING
        result.updated_nodes.append(node)

        # 2. Command (Signal)
        cmd = RuntimeCommand(
            type=CommandType.DISPATCH,
            target_node_id=node.node_id,
            payload={}
        )
        result.commands.append(cmd)

        return True

    # =========================================================================
    # Helpers
    # =========================================================================

    def _simulate_spawn(
        self,
        node_id: str,
        blueprint,
        resolved_path: str,
        context_vars: Dict[str, Any] = None,
        parent_context: ContextSchema = None,
        params_override: Dict[str, Any] = None  # <--- [NEW] 追加引数
    ) -> ProcessNode:
        """
        [Physics Helper] 完全なProcessNodeオブジェクトをメモリ上に生成する。

        Physics Rules:
          1. Context Inheritance & Shifting:
             親の変数を継承し、ネストされたループ変数 ($LOOP -> $LOOP^1) をシフトする。
          2. Variable Override:
             Strategyが指定した新しい変数 ($LOOP, $KEY) で上書きする。
          3. Params Override:
             Strategyが指定した動的パラメータ (items等) で静的定義を上書きする。
          4. Wiring Resolution:
             コンテキストに基づき、BlueprintのWiring定義内の変数を解決・フィルタリングする。
        """
        # 0. Extract Children Blueprints
        children_bps = []
        if blueprint.children:
            children_bps = blueprint.children
        elif blueprint.contents:
            children_bps = [blueprint.contents]

        # 1. Inherit & Shift System Variables
        inherited_sys = {}
        inherited_user = {}

        if parent_context:
            inherited_user = parent_context.user_variables.copy()

            # [Logic] Context Key Shifting
            # 新しいコンテキスト変数が「$LOOP」や「$KEY」を注入しようとしている場合（= 新しいスコープ）、
            # 親から継承する $LOOP 系変数の深度をシフトする。
            should_shift = context_vars and ("$LOOP" in context_vars or "$KEY" in context_vars)

            for k, v in parent_context.system_variables.items():
                if should_shift and k.startswith("$LOOP"):
                    # $LOOP -> $LOOP^1
                    if k == "$LOOP":
                        inherited_sys["$LOOP^1"] = v
                    else:
                        # $LOOP^N -> $LOOP^{N+1}
                        try:
                            parts = k.split("^")
                            if len(parts) == 2:
                                depth = int(parts[1])
                                inherited_sys[f"$LOOP^{depth+1}"] = v
                        except ValueError:
                            pass  # 形式不正な変数は無視
                else:
                    # その他の変数はそのまま継承
                    inherited_sys[k] = v

        # 2. Override with Plan (Strategy) vars
        if context_vars:
            inherited_sys.update(context_vars)

        # Context初期化
        ctx = ContextSchema(
            system_variables=inherited_sys,
            user_variables=inherited_user
        )

        # 3. Parameters Merge [NEW]
        # Blueprintの静的パラメータをベースに、Overrideを適用する。
        # Blueprint自体は変更せず、コピーに対して操作する。
        merged_params = blueprint.params.copy()
        if params_override:
            merged_params.update(params_override)

        # 4. Resolve Wiring
        # 解決済みのコンテキスト(ctx.system_variables)を使ってWiringを解決する
        # これにより {$LOOP-1} 等が物理的な値に置換され、無効な参照は除外される
        raw_wiring = blueprint.wiring or WiringObject()
        resolved_wiring = VariableResolver.resolve_wiring(raw_wiring, ctx.system_variables)

        return ProcessNode(
            node_id=node_id,
            stack_path=resolved_path,
            node_type=blueprint.node_type,
            opcode=blueprint.opcode,
            wiring=resolved_wiring,  # Resolved
            params=merged_params,    # <--- [NEW] Merged Paramsを使用
            children_blueprint=children_bps,
            lifecycle_status=LifecycleStatus.PENDING,
            runtime_context=ctx
        )

    def _select_strategy(self, opcode: OpCode):
        if opcode == OpCode.SERIAL: return SerialExpansionStrategy()
        elif opcode == OpCode.PARALLEL: return ParallelExpansionStrategy()
        elif opcode == OpCode.LOOP: return LoopExpansionStrategy()
        elif opcode == OpCode.ITERATE: return IterateExpansionStrategy()
        return None

    def _evaluate_suppression(self, snapshot, nodes, result):
        pass # 将来的な実装用

    def _evaluate_job_status(self, job, nodes, result):
        """ジョブ全体のステータス遷移判定"""
        
        # 1. 鎮火判定 (STOPPING -> CANCELLED)
        if job.status == JobStatus.STOPPING:
            running = [n for n in nodes.values() if n.lifecycle_status == LifecycleStatus.RUNNING]
            if not running:
                result.job_update = JobUpdate(status=JobStatus.CANCELLED)
            return

        # 2. 完了/失敗判定 (RUNNING -> ALL_DONE / FAILED)
        if job.status == JobStatus.RUNNING:
            # Rootノードが特定できない場合（Bootstrap前など）は何もしない
            if not job.root_node_id or job.root_node_id not in nodes:
                return

            root_node = nodes[job.root_node_id]

            # Case A: Rootが失敗 -> Jobも失敗
            if root_node.lifecycle_status == LifecycleStatus.FAILED:
                result.job_update = JobUpdate(status=JobStatus.FAILED)
            
            # Case B: Rootが正常完了 -> Jobは全工程完了 (ALL_DONE)
            elif root_node.lifecycle_status == LifecycleStatus.COMPLETED:
                result.job_update = JobUpdate(status=JobStatus.ALL_DONE)