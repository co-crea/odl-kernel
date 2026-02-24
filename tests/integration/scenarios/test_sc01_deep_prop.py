import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, BusinessResult, CommandType

# =========================================================================
# SECTION 1: SCENARIO DEFINITION (The "Variable" Part)
# テスト固有の入力データ（IR構造）をここに定義します。
# 読む人はここを見れば「どんな構造のテストか」が一目で分かります。
# =========================================================================

SCENARIO_ID = "sc01_deep_prop"

SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - serial:
        stack_path: root/serial_0/serial_0
        children:
          - worker:
              stack_path: root/serial_0/serial_0/worker_0
              agent: Writer
              mode: generate
              inputs: []
              output: Doc#default
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# テストの意図と前提条件をドキュメント化します。
# =========================================================================

class TestVerifyDeepAnalyzePropagation:
    """
    [Scenario: Deep Propagation Check]
    
    Intent (意図):
        1回のTick（Bootstrap）だけで、階層の深いWorkerまで一気に展開され、
        実行状態（RUNNING）になることを確認する。
        これにより「Deep Analyze」仕様（再帰的展開）が機能しているかを検証する。
        
    Structure (構造):
        Root(Serial) -> Wrapper(Serial) -> Worker(Generate)
    """

    # =========================================================================
    # SECTION 3: EXECUTION LOGIC (The "Procedure" Part)
    # シナリオ固有の操作手順とアサーションを記述します。
    # =========================================================================

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap Tick ---
        # 期待値: 一気に Worker の Dispatch まで進むこと
        result = sim.tick()
        sim.dump_analysis_result(result, "01_bootstrap")

        # [Verification] Deep Propagation
        # 1回のTickで、最深部のWorkerまで到達し、RUNNINGになっていること
        # 中間のSerialノードたちは展開済みだが、子供の完了待ちなのでRUNNING状態である
        sim.assert_simulation_state(
            running=["root/serial_0/serial_0/worker_0"]
        )

        # [Verification] Structural Integrity
        # 階層構造（Root -> Serial -> Serial -> Worker）が正しく物理化されているか
        sim.assert_hierarchy("root/serial_0", expected_children_count=1)          # Outer Serial
        sim.assert_hierarchy("root/serial_0/serial_0", expected_children_count=1) # Inner Serial

        # --- 3. Action: Completion ---
        # Generateモードなので、一発でNONE完了する
        # Worker完了 -> Inner Serial完了 -> Outer Serial完了 と一気に伝播するはず
        result_complete = sim.complete_node(path_suffix="worker_0")
        sim.dump_analysis_result(result_complete, "02_completion")

        # [Verification] Final State & Propagation
        # 全てのノードが完了しており、Runningなノードが残っていないこと
        sim.assert_simulation_state(
            running=[],
            completed=[
                "root/serial_0/serial_0/worker_0", # Child
                "root/serial_0/serial_0",          # Inner Parent
                "root/serial_0"                    # Root Parent
            ]
        )
        
        # 業務結果の確認
        sim.assert_node_status("worker_0", LifecycleStatus.COMPLETED, BusinessResult.NONE)