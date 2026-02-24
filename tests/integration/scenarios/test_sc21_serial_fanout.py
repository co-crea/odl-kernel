import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, JobStatus

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# 4拠点（TKY, OSA, FUK, SPR）によるシリアル・ファンアウトの物理検証
# =========================================================================

SCENARIO_ID = "sc21_serial_fanout_v4_complete"

SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - iterator_init:
        stack_path: root/serial_0/iterator_init_0
        source: "開催都市リスト:Cities@stable"
        item_key: "CityCode"
    - iterate:
        stack_path: root/serial_0/iterate_1
        strategy: serial
        contents:
          serial:
            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0
            children:
              - worker:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/worker_0
                  agent: Promoter
                  inputs: ["都市詳細.{$KEY}"]
                  output: "会場予約票#default/{$KEY}"
              - worker:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/worker_1
                  agent: Director
                  inputs:
                    - "会場予約票#default/{$KEY}"
                    - "セットリスト#{$HISTORY}"
                  output: "セットリスト#default/{$KEY}"
              - worker:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/worker_2
                  agent: MerchMgr
                  inputs: ["在庫管理簿#{$PREV}"]
                  output: "在庫管理簿#default/{$KEY}"
"""

class TestSc21SerialFanoutFull:
    """
    [Scenario: 4-Step Serial Fan-out with Global State Tracking]

    ## Verification Strategy (検証戦略):
    1.  [AnalysisResult Log] `complete_node` が生み出した「変化の瞬間」を逃さず記録。
    2.  [WorldState Log] `dump_world_state` により、特定の安定時点での「全ノードの状態」を俯瞰。
    3.  [Temporal Physics] Lazy Expansion（遅延展開）に基づき、生成タイミングに合わせた配線検証。
    """

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap & Data Resolve ---
        res_boot = sim.tick()
        sim.dump_analysis_result(res_boot, "01_bootstrap")
        sim.dump_world_state("01_bootstrap_world") # 初期状態の世界を記録

        mock_cities = {
            "TKY": {"CityCode": "TKY"}, "OSA": {"CityCode": "OSA"},
            "FUK": {"CityCode": "FUK"}, "SPR": {"CityCode": "SPR"}
        }
        res_data = sim.resolve_data(path_suffix="iterator_init_0", items=mock_cities)
        sim.dump_analysis_result(res_data, "02_data_resolved")
        sim.dump_world_state("02_data_resolved_world") # TKYが産まれた世界を記録

        # -----------------------------------------------------------
        # PHASE 1: TKY
        # -----------------------------------------------------------
        sim.complete_node(path_suffix="TKY/serial_0/worker_0")
        sim.complete_node(path_suffix="TKY/serial_0/worker_1")
        
        # [Wiring Check] worker_2 が生成された瞬間の配線を検証
        sim.assert_wiring("TKY/serial_0/worker_2", no_inputs=["在庫管理簿#{$PREV}"])
        
        # 【重要】結果そのものをダンプ（直後のtickは空になるため）
        res_tky = sim.complete_node(path_suffix="TKY/serial_0/worker_2")
        sim.dump_analysis_result(res_tky, "03_tky_phase_complete")
        sim.dump_world_state("03_tky_complete_world")

        # -----------------------------------------------------------
        # PHASE 2: OSA
        # -----------------------------------------------------------
        sim.complete_node(path_suffix="OSA/serial_0/worker_0")
        sim.complete_node(path_suffix="OSA/serial_0/worker_1")
        
        sim.assert_wiring("OSA/serial_0/worker_2", has_inputs=["在庫管理簿#default/TKY"])
        
        res_osa = sim.complete_node(path_suffix="OSA/serial_0/worker_2")
        sim.dump_analysis_result(res_osa, "04_osa_phase_complete")
        sim.dump_world_state("04_osa_complete_world")

        # -----------------------------------------------------------
        # PHASE 3: FUK (Relay & History Spreading Check)
        # -----------------------------------------------------------
        sim.complete_node(path_suffix="FUK/serial_0/worker_0")
        
        # [HISTORY Spreading] 過去分(TKY, OSA)が2つに展開されているか
        sim.assert_wiring("FUK/serial_0/worker_1", has_inputs=["セットリスト#default/TKY", "セットリスト#default/OSA"])
        sim.complete_node(path_suffix="FUK/serial_0/worker_1")

        # [PREV Recency] TKYは捨て、OSAのみを継承しているか
        sim.assert_wiring("FUK/serial_0/worker_2", has_inputs=["在庫管理簿#default/OSA"], no_inputs=["在庫管理簿#default/TKY"])
        
        res_fuk = sim.complete_node(path_suffix="FUK/serial_0/worker_2")
        sim.dump_analysis_result(res_fuk, "05_fuk_phase_complete")
        sim.dump_world_state("05_fuk_complete_world")

        # -----------------------------------------------------------
        # PHASE 4: SPR (Final Integration)
        # -----------------------------------------------------------
        sim.complete_node(path_suffix="SPR/serial_0/worker_0")
        
        # [HISTORY Spreading] 過去分(TKY, OSA, FUK)が3つに展開されているか
        sim.assert_wiring("SPR/serial_0/worker_1", has_inputs=[
            "セットリスト#default/TKY", "セットリスト#default/OSA", "セットリスト#default/FUK"
        ])
        sim.complete_node(path_suffix="SPR/serial_0/worker_1")

        sim.assert_wiring("SPR/serial_0/worker_2", has_inputs=["在庫管理簿#default/FUK"])
        
        res_final = sim.complete_node(path_suffix="SPR/serial_0/worker_2")
        sim.dump_analysis_result(res_final, "06_job_finalize")
        sim.dump_world_state("06_job_finalize_world")

        # -----------------------------------------------------------
        # FINAL GLOBAL ASSERTIONS
        # -----------------------------------------------------------
        assert sim.job.status == JobStatus.ALL_DONE
        sim.assert_hierarchy("root/serial_0/iterate_1", expected_children_count=4)