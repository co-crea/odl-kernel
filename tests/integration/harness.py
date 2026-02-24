import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

# L1 Types (Reference)
from odl.types import IrComponent, OpCode, NodeType, WiringObject, WorkerMode

# L0 Kernel Types
import odl_kernel
from odl_kernel.types import (
    Job, JobSnapshot, ProcessNode, JobStatus, LifecycleStatus,
    KernelEvent, KernelEventType, AnalysisResult, RuntimeCommand, CommandType,
    ContextSchema, BusinessResult
)

class KernelSimulator:
    """
    ODL Kernel In-Memory Execution Environment (Test Harness).

    ## 1. Role & Responsibility (役割と責務)
    このクラスは、ODLランタイムにおける **"Host (Cortex)"** の役割を、
    テスト用にインメモリで模倣（Emulation）する実験装置です。
    DBや外部APIを持たない代わりに、Pythonのオブジェクトとして「世界の全て」を保持します。

    ## 2. Architecture Principles (アーキテクチャ原則)

    ### A. Deep Analyze Assumption (一気通貫の物理法則)
    `odl_kernel.analyze()` は、「1回の呼び出しで、物理的に進行可能な限界（Action待ち or 完全停止）まで
    内部でサイクルを回し続け、収束した結果を一括で返却する」仕様です。
    したがって、本ハーネスは `tick()` をループさせる制御（Burst Logic）を持ちません。
    `tick()` を1回呼べば、世界は次の「安定状態」まで瞬時に遷移します。

    ### B. Signal vs State (シグナルと状態の分離)
    Kernelの出力 (`AnalysisResult`) は、以下の2系統で処理されます：

    * **State (The Truth):** `updated_nodes`
        * 状態の「真実」です。ステータス変更、新規生成、コンテキスト更新など、全てのデータはここにあります。
        * Host（本ハーネス）は、これを無条件にDB（`self.nodes`）にUPSERTします。

    * **Signal (The Event):** `commands`
        * 外部への「通知」や「副作用」のトリガーです。
        * `SPAWN_CHILD` や `TRANSITION` のPayloadは空（または最小限）であり、
          データ復元用ではなく「何が起きたか」のイベント識別としてのみ使用されます。

    ### C. Smart Completion (結果の自動判定)
    テストシナリオの記述性を高めるため、`complete_node()` は対象ノードの `mode` や `opcode` を分析し、
    文脈に応じた「あるべき結果（Success/Reject）」を自動的に決定します。
    特に `validate` モードにおける「1回目Reject -> 2回目Success」のステートフルな挙動をエミュレートします。
    """

    def __init__(self, ir_root: IrComponent, job_id: str = "test-job-001"):
        # 1. Initialize Job
        self.job = Job(
            job_id=job_id,
            status=JobStatus.RUNNING,
            ir_root=ir_root,
            global_context={}
        )

        # 2. In-Memory Database (str -> ProcessNode)
        self.nodes: Dict[str, ProcessNode] = {}

        # 3. Simulation Clock
        self.current_time = datetime.now()

        # 4. Logs & Metrics
        # 実行された全コマンドの履歴（順序保証）
        self.command_history: List[RuntimeCommand] = []

        # Smart Completion用: "OpCode:Agent" ごとの検証試行回数カウンタ
        self.validation_attempts: Dict[str, int] = defaultdict(int)

    # =========================================================================
    # Core Simulation Interface (Main Entry Points)
    # =========================================================================

    def tick(self, delta_seconds: float = 0.1) -> AnalysisResult:
        """
        [Atomic Step]
        物理時間を進め、Analyzeサイクルを回します。
        Deep Analyze仕様により、この1回の呼び出しで、連鎖的なノード生成や遷移が
        一括して実行される（コマンドリストとして返却される）ことを期待します。
        """
        self.current_time += timedelta(seconds=delta_seconds)

        # 1. Load Snapshot
        snapshot = JobSnapshot(job=self.job, nodes=self.nodes)

        # 2. Fire Tick Event
        event = KernelEvent(type=KernelEventType.TICK, occurred_at=self.current_time)

        # 3. Analyze (Pure Physics - Deep Execution)
        result = odl_kernel.analyze(snapshot, event)

        # 4. Apply Side Effects (Host Logic)
        self._apply_result(result)

        return result

    def complete_node(self, node_id: str = None, path_suffix: str = None) -> AnalysisResult:
        """
        [Smart Action]
        指定されたActionノードを、その特性に応じた結果で完了させ、Analyzeサイクルを回します。

        Note:
          - node_id または path_suffix のいずれかが必須です。
          - 対象ノードは RUNNING 状態であることを期待します。
        """
        # 1. Resolve Target
        target_node = self._resolve_target_node(node_id, path_suffix)
        if not target_node:
            raise ValueError(f"Target node not found. ID={node_id}, Suffix={path_suffix}")

        if target_node.lifecycle_status != LifecycleStatus.RUNNING:
            print(f"[WARN] Completing a node that is not RUNNING: {target_node.stack_path} ({target_node.lifecycle_status})")

        # 2. Decide Outcome (Auto Decision)
        result_type, output = self._decide_outcome(target_node)

        # 3. Fire Event & Analyze
        event = KernelEvent(
            type=KernelEventType.ACTION_COMPLETED,
            target_node_id=target_node.node_id,
            occurred_at=self.current_time + timedelta(seconds=0.1),
            payload={
                "result": result_type,
                "output_data": output
            }
        )
        # イベント送信 -> Analyze -> 結果適用までを一気に行う
        return self._send_event_internal(event)

    def resolve_data(self, node_id: str = None, path_suffix: str = None, items: List[Any] = None, resolved_id: str = None) -> AnalysisResult:
        """
        [Interaction Helper]
        Logicノード（iterator_init, scope_resolve）からのデータ要求 (REQUIRE_DATA) に対し、
        解決結果 (DATA_RESOLVED) を返信して処理を再開させます。

        Args:
            node_id (str): 対象ノードID (指定しない場合はpath_suffixを使用)
            path_suffix (str): 対象ノードを特定するパス末尾
            items (List[Any]): iterator_init 用の解決データリスト
            resolved_id (str): scope_resolve 用の解決済み物理ID

        Returns:
            AnalysisResult: データ解決後の再計算結果 (DATA_RESOLVEDイベントに対する応答)
        """
        # 1. Resolve Target
        target_node = self._resolve_target_node(node_id, path_suffix)
        if not target_node:
            raise ValueError(f"Target node not found. ID={node_id}, Suffix={path_suffix}")

        # 2. Construct Payload (Polymorphic)
        payload = {}
        if items is not None:
            payload["items"] = items
        if resolved_id is not None:
            payload["resolved_id"] = resolved_id

        # Validate: At least one payload must be provided
        if not payload:
             raise ValueError("Either 'items' or 'resolved_id' must be provided for resolve_data().")

        # 3. Fire Event & Analyze
        # DATA_RESOLVED イベントを発行し、Kernelにデータを渡す
        event = KernelEvent(
            type=KernelEventType.DATA_RESOLVED,
            target_node_id=target_node.node_id,
            occurred_at=self.current_time + timedelta(seconds=0.1),
            payload=payload
        )
        
        # イベント送信 -> Analyze -> 結果適用を一気に行う
        return self._send_event_internal(event)

    def _send_event_internal(self, event: KernelEvent) -> AnalysisResult:
        """内部共通: イベント送信処理"""
        if event.occurred_at > self.current_time:
            self.current_time = event.occurred_at

        snapshot = JobSnapshot(job=self.job, nodes=self.nodes)
        result = odl_kernel.analyze(snapshot, event)
        self._apply_result(result)
        return result

    # =========================================================================
    # Smart Logic (Outcome Decision)
    # =========================================================================

    def _decide_outcome(self, node: ProcessNode) -> Tuple[BusinessResult, Any]:
        mode = node.params.get("mode")
        agent = node.params.get("agent", "Unknown")
        opcode = node.opcode

        # 論理パスキーの生成（vNをマスク）
        # これをApproverとValidatorの両方で使う
        logical_path_key = re.sub(r'/v\d+', '/v*', node.stack_path)

        # Pattern 1: Dialogue -> Always Success (Done)
        if opcode == OpCode.DIALOGUE:
            return BusinessResult.NONE, {"comment": "Approved by Human (Auto)"}

        # Pattern 1.5: Approver (Gatekeeper) -> Reject (1st) -> Success (2nd)
        if node.opcode == OpCode.APPROVER:
            # 修正: Agent名だけでなく、論理パスも含めてユニークにする
            key = f"Approver:{logical_path_key}" 
            self.validation_attempts[key] += 1

            if self.validation_attempts[key] == 1:
                return BusinessResult.REJECT, {"comment": "品質不足により差し戻し (Auto)"}
            else:
                return BusinessResult.SUCCESS, {"comment": "基準を満たしたため承認 (Auto)"}

        # Pattern 2: Worker (Generate) -> Always Success
        if mode == WorkerMode.GENERATE:
            return BusinessResult.NONE, {"artifact": f"Draft generated by {agent}"}

        # Pattern 3: Worker (Validate) -> Reject (1st) -> Success (2nd)
        if mode == WorkerMode.VALIDATE:
            # 修正: 既に上で生成した logical_path_key を使う
            key = f"{opcode}:{logical_path_key}"
            self.validation_attempts[key] += 1

            if self.validation_attempts[key] == 1:
                return BusinessResult.REJECT, {"reason": "1st attempt rejection (Auto)"}
            else:
                return BusinessResult.SUCCESS, {"reason": "2nd attempt approval (Auto)"}

        # Default Fallback
        return BusinessResult.NONE, {}

    # =========================================================================
    # Host Emulation (Applying Results)
    # =========================================================================

    def _apply_result(self, result: AnalysisResult):
        """
        AnalysisResult（コマンド群）をインメモリ状態に適用します。

        Architectural Note:
            `result.updated_nodes` を「正（Truth）」として扱います。
            コマンドのPayloadからデータを復元するのではなく、計算済みのノード状態を
            そのままDB（self.nodes）に保存することで状態遷移を実現します。
        """
        # 1. Job Status Update
        if result.job_update and result.job_update.status:
            self.job.status = result.job_update.status

        # 2. Node State Update (UPSERT - The Truth)
        # Analyzerが計算した「最新の状態」をDBに保存します。
        # これにより、SPAWNされたノードや遷移したステータスは全て反映されます。
        for node in result.updated_nodes:
            self.nodes[node.node_id] = node

        # 3. Command Execution (The Signal)
        # ログ記録や外部副作用のトリガーとして使用します。
        # 状態更新はすでに完了しているため、ここでself.nodesを操作する必要はありません。
        for cmd in result.commands:
            self.command_history.append(cmd)

            if cmd.type == CommandType.SPAWN_CHILD:
                if cmd.payload.get("is_root"):
                    self.job.root_node_id = cmd.payload["child_node_id"]
                # ログ出力のみ（ノードは保存済み）
                pass
            elif cmd.type == CommandType.TRANSITION:
                pass
            elif cmd.type == CommandType.FINALIZE:
                pass
            elif cmd.type == CommandType.DISPATCH:
                # 外部APIコール等の副作用があればここに記述
                # 実際にはWorker APIへのHTTP POSTなどが発生する箇所
                pass
            elif cmd.type == CommandType.REQUIRE_DATA:
                # Host側でのデータ解決待ち（非同期）
                # テストコード側で sim.resolve_data() を呼び出して応答することを期待する
                pass

    # =========================================================================
    # Physics Assertions (Verification Toolkit)
    # =========================================================================

    def assert_node_status(self, path_suffix: str, status: LifecycleStatus, result: BusinessResult = None):
        """
        [Basic Assertion]
        特定ノードの状態をアサートします。
        パスサフィックスで指定できるため、IDを知らなくても検証可能です。
        """
        node = self._resolve_target_node(None, path_suffix)
        assert node is not None, f"Node not found with suffix: ...{path_suffix}"

        assert node.lifecycle_status == status, \
            f"Status mismatch for ...{path_suffix}: expected {status}, got {node.lifecycle_status}"

        if result:
            assert node.business_result == result, \
                f"BusinessResult mismatch for ...{path_suffix}: expected {result}, got {node.business_result}"

    def assert_simulation_state(self, running: List[str] = None, completed: List[str] = None):
        """
        [Macro State Assertion]
        シミュレーション全体の「断面」を一括検証します。
        指定されたパス(suffix)を持つノードが、期待された状態（Running/Completed）にあるかをチェックします。

        Intent:
            「今、誰が動いていて、誰が終わったのか？」というマクロな視点で状態を固定化します。
            また、予期せぬノードがRunningになっていないか（過剰実行）も警告します。

        Args:
            running: RUNNINGであるべきノードのパスsuffixリスト
            completed: COMPLETEDであるべきノードのパスsuffixリスト
        """
        running = running or []
        completed = completed or []

        # 1. Check Running Nodes
        for suffix in running:
            self.assert_node_status(suffix, LifecycleStatus.RUNNING)

        # 2. Check Completed Nodes
        for suffix in completed:
            self.assert_node_status(suffix, LifecycleStatus.COMPLETED)

        # 3. Exclusive Running Check (Leak Detection)
        # 「指定されたもの以外が動いていないこと」を確認するための緩やかなガード
        actual_running_nodes = self.get_running_nodes()
        actual_running_paths = [n.stack_path for n in actual_running_nodes]

        if len(actual_running_nodes) != len(running):
            print(f"\n[WARN] Running nodes count mismatch.")
            print(f"  Expected ({len(running)}): {running}")
            print(f"  Actual   ({len(actual_running_nodes)}): {[p.split('/')[-1] for p in actual_running_paths]}")

    def assert_hierarchy(self, parent_suffix: str, expected_children_count: int, child_suffix_pattern: str = None):
        """
        [Structural Integrity Assertion]
        Controlノードが「産んだ子供」の数と、その子供のパスパターンを検証します。

        Intent:
            - Loopの回数が正しいか（例: 3回ループなら3つの子がいるか）
            - Parallelが一括生成（Batch Expansion）を行っているか
            - Serialが過剰に子供を産んでいないか（Lazy Expansion）

        Args:
            parent_suffix: 親ノードを特定するパス
            expected_children_count: 期待される子供の数 (runtime_context.children_idsの長さ)
            child_suffix_pattern: 子供のパスに含まれるべき文字列 (Optional)
        """
        parent = self._resolve_target_node(None, parent_suffix)
        assert parent is not None, f"Parent node not found: ...{parent_suffix}"

        # 実際の子供たちを取得
        children_ids = parent.runtime_context.children_ids
        children = [self.nodes[cid] for cid in children_ids if cid in self.nodes]

        # 1. Count Check
        assert len(children) == expected_children_count, \
            f"Children count mismatch for {parent_suffix}: expected {expected_children_count}, got {len(children)}"

        # 2. Pattern Check
        if child_suffix_pattern:
            for child in children:
                assert child_suffix_pattern in child.stack_path, \
                    f"Child path schema mismatch: {child.stack_path} does not contain '{child_suffix_pattern}'"

    def assert_absent(self, path_suffix: str):
        """
        [Negative Assertion]
        「まだ存在してはならない」ノードが存在しないことを検証します。

        Intent:
            - Lazy Expansion (Loopの次世代やSerialの次工程) が正しく待機しているか
            - break_on 条件により生成が抑制されたか
        """
        node = self._resolve_target_node(None, path_suffix)
        if node is not None:
            raise AssertionError(
                f"Node SHOULD BE ABSENT but found: {node.stack_path} (Status: {node.lifecycle_status})"
            )

    def assert_context(self, path_suffix: str, key: str, value: Any):
        """
        [Context Physics Assertion]
        ノードに注入されたコンテキスト変数（$LOOP, $KEYなど）の値を検証します。

        Intent:
            - 変数注入ロジック ($LOOP, $PREV) が正しく機能しているか
            - Iterateにおける $KEY, $ITEM が正しく渡されているか

        Args:
            path_suffix: ノードを特定するパス
            key: 変数キー (e.g. "$LOOP", "count")
            value: 期待値
        """
        node = self._resolve_target_node(None, path_suffix)
        assert node is not None, f"Node not found: ...{path_suffix}"

        # System Variables ($Prefix) vs User Variables
        if key.startswith("$"):
            actual = node.runtime_context.system_variables.get(key)
        else:
            actual = node.runtime_context.user_variables.get(key)

        assert actual == value, \
            f"Context mismatch in {path_suffix} for '{key}': expected {value}, got {actual}"

    # =========================================================================
    # Physics Assertions (Verification Toolkit)
    # =========================================================================

    def assert_not_spawned(self, path_suffix: str):
        """
        [Negative Physics Assertion] 指定されたノードが未生成であることを検証します。

        ## Why this is important (検証の意義):
        ODLの SerialStrategy や LoopStrategy は、"Lazy Expansion（遅延展開）" という
        物理法則に従います。
        これは「前工程が完了するまで、次工程のノードをこの世に産み出さない」という制約です。

        このアサーションを用いることで、以下の異常系を検知できます：
        1. State Leak: Serial設定なのに、後続ノードがフライングして生成されている。
        2. Batching Bug: 並列実行（Parallel）のロジックが直列実行に混入している。
        3. Break Condition Failure: 本来終了すべきループが、余分な次世代を生成している。

        Args:
            path_suffix (str): 生成されていないことを期待するノードのパス末尾。
        """
        node = self._resolve_target_node(None, path_suffix)
        if node is not None:
            raise AssertionError(
                f"Physical Law Violation: Node SHOULD NOT be spawned yet, but found: {node.stack_path}\n"
                f"Current Status: {node.lifecycle_status}\n"
                f"Hint: Check if the ExpansionStrategy is correctly implementing Lazy Expansion."
            )

    def assert_wiring(self, path_suffix: str, has_inputs: List[str] = None, no_inputs: List[str] = None, output: str = None):
        """
        [Physics Assertion] ノードの配線がコンテキストに基づき解決・フィルタリングされているか検証します。

        ## Why this is important (検証の意義):
        ODLカーネルの VariableResolver は、ノードが生成される「瞬間」のコンテキストを用いて
        変数（$LOOP, $PREV等）を物理IDへ置換します。

        この検証が必要な理由は以下の通りです：
        1. Context Relay Check: $PREV が「直前」の物理IDを正しく指しているか。
        2. Spreading Check: $HISTORY がリストとして複数の入力に展開されているか。
        3. Existence Filtering: v{$LOOP-1} が Loop=1 の時に「生存不能」として除外されているか。

        ## Note on Timing (実行タイミングの注意):
        Serial実行において、この関数は「対象ノードが生成された後」かつ「完了する前」に呼ぶ必要があります。
        Analyzerは Action ノードの実行指示（DISPATCH）を出した時点で計算を止めるため、
        適切な sim.complete_node() の呼び出しによって時間を進める必要があります。

        Args:
            path_suffix: 対象ノードを特定するパスサフィックス。
            has_inputs: 存在すべき物理IDリスト。
            no_inputs: 存在してはならない（フィルタリングされるべき）IDリスト。
            output: 解決後の期待される出力ID。
        """
        node = self._resolve_target_node(None, path_suffix)
        
        # 物理的未生成状態に対する親切なエラー通知
        if node is None:
            # デバッグをしやすくするため、現在メモリにあるノードをリストアップする
            current_nodes = [n.stack_path.split('/')[-1] for n in self.nodes.values()]
            raise AssertionError(
                f"Temporal Paradox: Node not found with suffix: ...{path_suffix}\n"
                f"Why: This often happens in Serial flows where the node isn't spawned until the PREVIOUS node completes.\n"
                f"Currently spawned nodes: {current_nodes}"
            )

        actual_inputs = node.wiring.inputs

        # 1. Check required inputs (Presence)
        if has_inputs:
            for expected in has_inputs:
                assert expected in actual_inputs, \
                    f"Wiring Failure: Missing expected input '{expected}' in {path_suffix}.\nActual inputs: {actual_inputs}"

        # 2. Check excluded inputs (Absence)
        if no_inputs:
            for unexpected in no_inputs:
                assert unexpected not in actual_inputs, \
                    f"Physics Violation: Unexpected input '{unexpected}' found in {path_suffix} (Should be filtered).\nActual inputs: {actual_inputs}"

        # 3. Check output resolution
        if output:
            assert node.wiring.output == output, \
                f"Output Resolution Failure for {path_suffix}: expected '{output}', got '{node.wiring.output}'"

    # =========================================================================
    # Helpers & Debugging
    # =========================================================================

    def _resolve_target_node(self, node_id: str, path_suffix: str) -> Optional[ProcessNode]:
        """IDまたはパスサフィックスからノードを特定します。"""
        if node_id:
            return self.nodes.get(node_id)
        if path_suffix:
            # パス後方一致で検索。複数ある場合は「最新（リストの後ろ）」かつ「RUNNING」を優先
            candidates = [n for n in self.nodes.values() if n.stack_path.endswith(path_suffix)]
            if not candidates:
                return None

            running = [n for n in candidates if n.lifecycle_status == LifecycleStatus.RUNNING]
            if running:
                return running[-1]
            return candidates[-1]
        return None

    def get_running_nodes(self) -> List[ProcessNode]:
        """現在RUNNING状態にあるAction/Logicノードを取得します（デバッグ用）。"""
        return [
            n for n in self.nodes.values()
            if n.lifecycle_status == LifecycleStatus.RUNNING
            and n.node_type in (NodeType.ACTION, NodeType.LOGIC)
        ]

    def dump_analysis_result(self, result: AnalysisResult, step_label: str) -> None:
        """
        [Debug Helper]
        Analyze結果（AnalysisResult）の内容をJSON形式でログファイルに出力します。
        出力先: tests/integration/logs/{job_id}_{step_label}.json
        """
        # 1. Prepare Directory
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # 2. Construct Filename
        filename = f"{self.job.job_id}_{step_label}.log"
        file_path = log_dir / filename

        # 3. Serialize Content
        # exclude_none=True にすると、Noneのフィールドが消えて見やすくなります
        json_content = result.model_dump_json(indent=2, exclude_none=True)

        # 4. Add Header Context
        header = f"--- Analysis Result Log ---\n"
        header += f"Time: {self.current_time}\n"
        header += f"Step: {step_label}\n"
        header += f"---------------------------\n"

        # 5. Write to File
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(header + json_content)
            print(f"\n[Log Dumped] {file_path}")
        except Exception as e:
            print(f"[Log Error] Failed to dump result: {e}")

    def dump_world_state(self, step_label: str):
        """
        [Debug Helper] 現在の「世界の全状態」をJSON形式でダンプします。

        ## Why this is important:
        `dump_analysis_result` は、特定のイベントによる「変化（Delta）」のみを記録します。
        しかし、複雑なファンアウトでは「今、誰がどのステータスで存在しているか」という
        全体像（The Truth）を把握することが、デバッグの鍵となります。

        出力先: tests/integration/logs/{job_id}_{step_label}_world.json
        """
        # 現在の最新Snapshotを作成
        snapshot = JobSnapshot(job=self.job, nodes=self.nodes)
        
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_path = log_dir / f"{self.job.job_id}_{step_label}_world.log"

        # Pydanticのシリアライズ機能を使用して全ノードの状態を書き出し
        json_content = snapshot.model_dump_json(indent=2, exclude_none=True)
        
        header = f"--- Global World State Log ---\n"
        header += f"Time: {self.current_time}\n"
        header += f"Step: {step_label}\n"
        header += f"------------------------------\n"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(header + json_content)
        print(f"\n[World State Dumped] {file_path}")