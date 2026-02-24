import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# Adopted from cocrea.5120.yml - Case 2_2_2 (Expansion IR)
# =========================================================================

SCENARIO_ID = "sc22_fanout_team"

# Case 2_2_2: Parallel Fan-out containing Generate Team with Multiple Validators
# Source: fan_out > generate_team (parallel strategy)
SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - iterator_init:
        stack_path: root/serial_0/iterator_init_0
        source: 言語リスト:Languages@stable
        item_key: LangCode
    - iterate:
        stack_path: root/serial_0/iterate_1
        strategy: parallel
        contents:
          serial:
            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0
            children:
              - loop:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0
                  count: 5
                  break_on: success
                  contents:
                    serial:
                      stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0
                      children:
                        - worker:
                            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0/worker_0
                            agent: Translator
                            mode: generate
                            inputs:
                              - 原文テキスト:SourceText@stable
                              - 言語規定.{$KEY}
                              - 翻訳テキスト#default/{$KEY}/v{$LOOP-1}
                              - 翻訳テキスト__Review_Linguistic_QA#default/{$KEY}/v{$LOOP-1}
                              - 翻訳テキスト__Review_Legal_Check#default/{$KEY}/v{$LOOP-1}
                            output: 翻訳テキスト#default/{$KEY}/v{$LOOP}
                        - parallel:
                            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1
                            children:
                              - worker:
                                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_0
                                  agent: Linguistic_QA
                                  mode: validate
                                  inputs:
                                    - 原文テキスト:SourceText@stable
                                    - 言語規定.{$KEY}
                                    - 翻訳テキスト#default/{$KEY}/v{$LOOP}
                                  output: 翻訳テキスト__Review_Linguistic_QA#default/{$KEY}/v{$LOOP}
                              - worker:
                                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_1
                                  agent: Legal_Check
                                  mode: validate
                                  inputs:
                                    - 原文テキスト:SourceText@stable
                                    - 言語規定.{$KEY}
                                    - 翻訳テキスト#default/{$KEY}/v{$LOOP}
                                  output: 翻訳テキスト__Review_Legal_Check#default/{$KEY}/v{$LOOP}
              - scope_resolve:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/scope_resolve_1
                  target: 翻訳テキスト
                  from_scope: loop
                  strategy: take_latest_success
                  map_to: 翻訳テキスト#default/{$KEY}
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc22FanoutTeam:
    """
    [Scenario: Fan-out with Generate Team (Case 2_2_2)]
    
    Verification Strategy:
        sc21と同様に、Phaseごとの「世界の断面 (World State)」を記録し、
        並列実行（Parallel Strategy）と独立したループ進行（Deep Stacking）を可視化する。
    """

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap ---
        # Root (Serial) -> Iterator Init
        res_boot = sim.tick()
        sim.dump_analysis_result(res_boot, "01_bootstrap")
        sim.dump_world_state("01_bootstrap_world")

        # --- 3. Action: Data Resolution (Parallel Expansion Trigger) ---
        # 日本語(JA)と英語(EN)の2並列展開
        mock_langs = {
            "JA": {"LangCode": "JA", "Note": "Japanese"},
            "EN": {"LangCode": "EN", "Note": "English"}
        }
        res_data = sim.resolve_data(path_suffix="iterator_init_0", items=mock_langs)
        
        sim.dump_analysis_result(res_data, "02_data_resolved")
        sim.dump_world_state("02_data_resolved_world")

        # [Verification] Parallel Launch
        # JAとEN、それぞれのチームのGenerator (v1) が同時に起動していること
        sim.assert_simulation_state(
            running=[
                "iterate_1/JA/serial_0/loop_0/v1/serial_0/worker_0", # JA Translator
                "iterate_1/EN/serial_0/loop_0/v1/serial_0/worker_0"  # EN Translator
            ]
        )


        # -----------------------------------------------------------
        # PHASE 1: JA Branch - Cycle 1 (Feedback Loop Validation)
        # -----------------------------------------------------------
        # JAチームだけ先行して進め、ENチームが待機状態であることを確認する
        sim.complete_node(path_suffix="JA/serial_0/loop_0/v1/serial_0/worker_0") # Gen
        sim.complete_node(path_suffix="JA/serial_0/loop_0/v1/serial_0/parallel_1/worker_0") # Val1 (Reject)
        
        # Val2 Reject -> Loop Turnaround -> v2 Generation
        res_ja_v1 = sim.complete_node(path_suffix="JA/serial_0/loop_0/v1/serial_0/parallel_1/worker_1")
        
        sim.dump_analysis_result(res_ja_v1, "03_ja_v1_reject")
        sim.dump_world_state("03_ja_v1_reject_world")

        # [Verification] Asynchronous Progress
        # JAは v2 に進んでいるが、ENは v1 のままであること（干渉しないこと）
        sim.assert_simulation_state(
            running=[
                "iterate_1/JA/serial_0/loop_0/v2/serial_0/worker_0",
                "iterate_1/EN/serial_0/loop_0/v1/serial_0/worker_0"
            ]
        )

        # [Verification] Complex ID Wiring
        # JA v2 Generatorが「前回の自分」と「前回のValidator指摘」を受け取っているか
        ja_v2_worker = "iterate_1/JA/serial_0/loop_0/v2/serial_0/worker_0"
        sim.assert_context(ja_v2_worker, "$LOOP", 2)
        sim.assert_wiring(
            ja_v2_worker,
            has_inputs=[
                "言語規定.JA",                                      # Item Injection
                "翻訳テキスト#default/JA/v1",                       # Previous Self
                "翻訳テキスト__Review_Linguistic_QA#default/JA/v1", # Feedback 1
                "翻訳テキスト__Review_Legal_Check#default/JA/v1"    # Feedback 2
            ]
        )


        # -----------------------------------------------------------
        # PHASE 2: EN Branch - Cycle 1 (Catch up)
        # -----------------------------------------------------------
        # ENチームも進める
        sim.complete_node(path_suffix="EN/serial_0/loop_0/v1/serial_0/worker_0")
        sim.complete_node(path_suffix="EN/serial_0/loop_0/v1/serial_0/parallel_1/worker_0")
        res_en_v1 = sim.complete_node(path_suffix="EN/serial_0/loop_0/v1/serial_0/parallel_1/worker_1")

        sim.dump_analysis_result(res_en_v1, "04_en_v1_reject")
        sim.dump_world_state("04_en_v1_reject_world")

        # [Verification] 両チームとも v2 に突入
        sim.assert_simulation_state(
            running=[
                "iterate_1/JA/serial_0/loop_0/v2/serial_0/worker_0",
                "iterate_1/EN/serial_0/loop_0/v2/serial_0/worker_0"
            ]
        )


        # -----------------------------------------------------------
        # PHASE 3: Cycle 2 Success (Convergence)
        # -----------------------------------------------------------
        # JA v2 Success
        sim.complete_node(path_suffix="JA/serial_0/loop_0/v2/serial_0/worker_0")
        sim.complete_node(path_suffix="JA/serial_0/loop_0/v2/serial_0/parallel_1/worker_0")
        sim.complete_node(path_suffix="JA/serial_0/loop_0/v2/serial_0/parallel_1/worker_1")

        # EN v2 Success
        sim.complete_node(path_suffix="EN/serial_0/loop_0/v2/serial_0/worker_0")
        sim.complete_node(path_suffix="EN/serial_0/loop_0/v2/serial_0/parallel_1/worker_0")
        
        # Last Action triggers Scope Resolution Wait
        res_cycle2 = sim.complete_node(path_suffix="EN/serial_0/loop_0/v2/serial_0/parallel_1/worker_1")
        
        sim.dump_analysis_result(res_cycle2, "05_cycles_complete")
        sim.dump_world_state("05_cycles_complete_world")

        # [Verification] Scope Resolve Waiting
        # Loopが完了し、ScopeResolveがデータ待ち状態になっていること
        sim.assert_node_status("iterate_1/JA/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)
        sim.assert_node_status("iterate_1/EN/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)


        # -----------------------------------------------------------
        # PHASE 4: Final Resolution
        # -----------------------------------------------------------
        # Host Response: JA
        sim.resolve_data(
            path_suffix="JA/serial_0/scope_resolve_1",
            resolved_id="翻訳テキスト#default/JA/v2"
        )
        
        # Host Response: EN
        res_final = sim.resolve_data(
            path_suffix="EN/serial_0/scope_resolve_1",
            resolved_id="翻訳テキスト#default/EN/v2"
        )

        sim.dump_analysis_result(res_final, "06_all_done")
        sim.dump_world_state("06_all_done_world")

        # [Verification] Final State
        sim.assert_simulation_state(
            running=[],
            completed=[
                "iterate_1/JA/serial_0",
                "iterate_1/EN/serial_0",
                "iterate_1",
                "root/serial_0"
            ]
        )