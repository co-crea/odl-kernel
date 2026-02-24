import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc13_ensemble"

SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    # 1. Diverge (発散): Generator x Samples 分の並列実行
    - parallel:
        stack_path: root/serial_0/parallel_0
        children:
          # PlannerA の 2案
          - worker:
              stack_path: root/serial_0/parallel_0/worker_0
              agent: PlannerA
              mode: generate
              inputs: [市場トレンド:Trend2025@latest]
              output: _アイデアリスト#default/PlannerA/1
          - worker:
              stack_path: root/serial_0/parallel_0/worker_1
              agent: PlannerA
              mode: generate
              inputs: [市場トレンド:Trend2025@latest]
              output: _アイデアリスト#default/PlannerA/2
          # VeteranB の 2案
          - worker:
              stack_path: root/serial_0/parallel_0/worker_2
              agent: VeteranB
              mode: generate
              inputs: [市場トレンド:Trend2025@latest]
              output: _アイデアリスト#default/VeteranB/1
          - worker:
              stack_path: root/serial_0/parallel_0/worker_3
              agent: VeteranB
              mode: generate
              inputs: [市場トレンド:Trend2025@latest]
              output: _アイデアリスト#default/VeteranB/2
    # 2. Converge (収束): 全成果物をInputに注入して集約
    - worker:
        stack_path: root/serial_0/worker_1
        agent: ProdManager
        mode: generate # 統合も「生成」の一種
        inputs:
          - 市場トレンド:Trend2025@latest
          - _アイデアリスト#default/PlannerA/1
          - _アイデアリスト#default/PlannerA/2
          - _アイデアリスト#default/VeteranB/1
          - _アイデアリスト#default/VeteranB/2
        output: アイデアリスト#default
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc13Ensemble:
    """
    [Scenario: Ensemble (Diverge & Converge)]

    Intent:
        1. Diverge (Parallel): 4つのWorkerが一括生成され、同時にRUNNINGになること。
        2. Synchronization: Parallelの全完了まで、後続のConvergeノードが生成されないこと。
        3. Converge (Serial): 全ての子の成果物が揃った時点で生成・実行されること。
    """

    # =========================================================================
    # SECTION 3: EXECUTION LOGIC
    # =========================================================================

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap ---
        result = sim.tick()
        sim.dump_analysis_result(result, "01_bootstrap")

        # [Verification] Diverge Phase (Batch Expansion)
        # Parallel配下の4つのWorkerが一斉に起動していること
        parallel_workers = [
            "root/serial_0/parallel_0/worker_0",
            "root/serial_0/parallel_0/worker_1",
            "root/serial_0/parallel_0/worker_2",
            "root/serial_0/parallel_0/worker_3"
        ]
        sim.assert_simulation_state(running=parallel_workers)

        # [Verification] Serial Wait (Lazy Expansion)
        # Converge担当のworker_1は、Parallelが終わるまで生成すらされないこと
        sim.assert_absent("root/serial_0/worker_1")


        # --- 3. Action: Partial Completion (Noise) ---
        # 4つのうち2つだけ完了させる (PlannerAの分)
        sim.complete_node(path_suffix="parallel_0/worker_0")
        result = sim.complete_node(path_suffix="parallel_0/worker_1")
        sim.dump_analysis_result(result, "02_partial_complete")

        # [Verification] Still Waiting
        # まだVeteranBが終わっていないので、Parallelは完了せず、Convergeも始まらない
        sim.assert_simulation_state(
            completed=[
                "root/serial_0/parallel_0/worker_0",
                "root/serial_0/parallel_0/worker_1"
            ],
            running=[
                "root/serial_0/parallel_0/worker_2",
                "root/serial_0/parallel_0/worker_3"
            ]
        )
        sim.assert_node_status("root/serial_0/parallel_0", LifecycleStatus.RUNNING)
        sim.assert_absent("root/serial_0/worker_1")


        # --- 4. Action: Full Completion (Convergence Trigger) ---
        # 残りの2つを完了させる (VeteranBの分)
        sim.complete_node(path_suffix="parallel_0/worker_2")
        # 最後の1つが完了 -> Parallel完了 -> Serialが次へ進む -> Converge生成 -> Dispatch
        result = sim.complete_node(path_suffix="parallel_0/worker_3")
        sim.dump_analysis_result(result, "03_full_diverge_complete")

        # [Verification] Converge Phase Start
        # Parallel全体が完了し、Convergeノードが起動していること
        sim.assert_node_status("root/serial_0/parallel_0", LifecycleStatus.COMPLETED)
        sim.assert_simulation_state(
            running=["root/serial_0/worker_1"]
        )

        # [Verification] Input Binding
        # 生成されたConvergeノードが、期待通りの入力IDを持っているか確認
        # (パラレル実行された4つの成果物をすべて受け取っているか)
        expected_inputs = [
            "市場トレンド:Trend2025@latest", # 外部入力
            "_アイデアリスト#default/PlannerA/1",
            "_アイデアリスト#default/PlannerA/2",
            "_アイデアリスト#default/VeteranB/1",
            "_アイデアリスト#default/VeteranB/2"
        ]
        sim.assert_wiring(
            path_suffix="root/serial_0/worker_1",
            has_inputs=expected_inputs
        )


        # --- 5. Action: Final Completion ---
        result = sim.complete_node(path_suffix="root/serial_0/worker_1")
        sim.dump_analysis_result(result, "04_all_done")

        # [Verification] Final State
        sim.assert_simulation_state(
            running=[],
            completed=["root/serial_0"]
        )
        # 修正: Generateモードの連鎖であるため、結果は承認(SUCCESS)ではなく完了(NONE)となるのが正しい
        sim.assert_node_status("root/serial_0", LifecycleStatus.COMPLETED, BusinessResult.NONE)