import pytest
from uuid import uuid4
from typing import List

from odl_kernel.types import IrComponent, OpCode, NodeType, WiringObject, ProcessNode, LifecycleStatus, BusinessResult

# Target Strategy
from odl_kernel.engine.logic.expansion.base import ExpansionStrategy
from odl_kernel.engine.logic.expansion.serial import SerialExpansionStrategy

class TestSerialExpansionStrategy:
    
    @pytest.fixture
    def strategy(self) -> ExpansionStrategy:
        return SerialExpansionStrategy()

    @pytest.fixture
    def mock_parent(self):
        """
        Serialの親ノードを生成するヘルパー。
        stack_path (親の物理パス) を指定可能にし、動的解決のテストに対応する。
        """
        def _create(blueprints: List[IrComponent], path: str = "root/serial_0") -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.CONTROL,
                opcode=OpCode.SERIAL,
                stack_path=path,
                wiring=WiringObject(inputs=[], output=None),
                children_blueprint=blueprints,
                params={}
            )
        return _create

    @pytest.fixture
    def mock_child(self):
        """
        状態検証用の子ノードを生成するヘルパー。
        """
        def _create(status: LifecycleStatus, path_suffix: str = "child") -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.ACTION,
                opcode=OpCode.WORKER,
                stack_path=f"root/serial_0/{path_suffix}",
                wiring=WiringObject(inputs=[], output=None),
                lifecycle_status=status
            )
        return _create

    # =========================================================================
    # Case 1: First Step (初期状態からの生成)
    # =========================================================================
    def test_plan_first_node(self, strategy: ExpansionStrategy, mock_parent):
        """
        [Happy Path] 子ノードが0個の場合、リストの先頭(Index 0)の計画を立てること。
        """
        bp1 = IrComponent(stack_path="root/serial_0/step_1", opcode=OpCode.WORKER)
        bp2 = IrComponent(stack_path="root/serial_0/step_2", opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp1, bp2], path="root/serial_0")
        current_children = [] # まだ誰もいない

        plans = strategy.plan_next_nodes(parent, current_children)

        # 検証
        assert len(plans) == 1
        plan = plans[0]
        
        # 1. Blueprintの一致
        assert plan.blueprint == bp1
        # 2. パス解決: 親パス + "/" + ノード名
        assert plan.resolved_path == "root/serial_0/step_1"
        # 3. インデックス: 0番目
        assert plan.original_index == 0
        # 4. コンテキスト: SerialはContext注入しない
        assert plan.context_vars == {}

    # =========================================================================
    # Case 2: Sequential Wait (待機)
    # =========================================================================
    def test_wait_for_running_child(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Flow Control] 直近の子ノードが完了(COMPLETED)していない場合、
        次のノードを生成せず待機すること（空リストを返す）。
        """
        bp1 = IrComponent(stack_path="root/serial_0/step_1", opcode=OpCode.WORKER)
        bp2 = IrComponent(stack_path="root/serial_0/step_2", opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp1, bp2])
        
        # 1人目がまだ実行中
        child1 = mock_child(status=LifecycleStatus.RUNNING, path_suffix="step_1")
        current_children = [child1]

        plans = strategy.plan_next_nodes(parent, current_children)

        # 待機
        assert len(plans) == 0

    # =========================================================================
    # Case 3: Progression (次ステップへの進行)
    # =========================================================================
    def test_plan_next_node_after_completion(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Happy Path] 直近の子ノードが完了している場合、次の順序(Index 1)の計画を立てること。
        """
        bp1 = IrComponent(stack_path="root/serial_0/step_1", opcode=OpCode.WORKER)
        bp2 = IrComponent(stack_path="root/serial_0/step_2", opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp1, bp2], path="root/serial_0")
        
        # 1人目が完了済み
        child1 = mock_child(status=LifecycleStatus.COMPLETED, path_suffix="step_1")
        current_children = [child1]

        plans = strategy.plan_next_nodes(parent, current_children)

        # 検証
        assert len(plans) == 1
        plan = plans[0]
        
        # 2番目のBlueprintが選ばれていること
        assert plan.blueprint == bp2
        assert plan.resolved_path == "root/serial_0/step_2"
        assert plan.original_index == 1 # インデックスが進んでいること
        assert plan.context_vars == {}

    # =========================================================================
    # Case 4: All Completed (完了)
    # =========================================================================
    def test_stop_expansion_when_all_completed(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Flow Control] 定義された全ての子ノードが生成済みの場合、それ以上計画を立てないこと。
        """
        bp1 = IrComponent(stack_path="root/serial_0/step_1", opcode=OpCode.WORKER)
        parent = mock_parent(blueprints=[bp1])
        
        # 全ての子が存在する
        child1 = mock_child(status=LifecycleStatus.COMPLETED)
        current_children = [child1]

        plans = strategy.plan_next_nodes(parent, current_children)

        assert len(plans) == 0

    # =========================================================================
    # Case 5: Halt on Failure (異常時の停止)
    # =========================================================================
    def test_halt_on_failure(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Resilience] 直近の子ノードが失敗(FAILED)した場合、
        次のノード生成に進まず停止すること。
        (親自身のFAILED遷移はTransitionRulesの責務だが、Strategyはここでストップする)
        """
        bp1 = IrComponent(stack_path="root/serial_0/step_1", opcode=OpCode.WORKER)
        bp2 = IrComponent(stack_path="root/serial_0/step_2", opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp1, bp2])
        
        # 1人目が失敗
        child1 = mock_child(status=LifecycleStatus.FAILED, path_suffix="step_1")
        
        plans = strategy.plan_next_nodes(parent, [child1])

        # 次は進まない
        assert len(plans) == 0

    # =========================================================================
    # Case 6: Nested Path Resolution (ネスト時の動的パス解決)
    # =========================================================================
    def test_nested_path_resolution(self, strategy: ExpansionStrategy, mock_parent):
        """
        [CRITICAL] 親がLoop内などで動的パス(v1)を持っている場合、
        Blueprintにトークン($LOOP)が含まれていても、親のパスを継承して正しく解決すること。
        
        Scenario:
          Parent Path: "root/loop_0/v1/serial_inner"
          Blueprint Path: "root/loop_0/v{$LOOP}/serial_inner/step_1" (コンパイル直後の状態)
          Expected Resolved: "root/loop_0/v1/serial_inner/step_1"
        """
        parent_resolved_path = "root/loop_0/v1/serial_inner"
        
        # 未解決トークンを含むBlueprintパス
        tokenized_path = "root/loop_0/v{$LOOP}/serial_inner/step_1"
        bp1 = IrComponent(stack_path=tokenized_path, opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp1], path=parent_resolved_path)
        
        plans = strategy.plan_next_nodes(parent, [])

        assert len(plans) == 1
        plan = plans[0]
        
        # 期待値: 親パスを継承し、トークンが排除されていること
        expected_path = "root/loop_0/v1/serial_inner/step_1"
        assert plan.resolved_path == expected_path
        assert "{$LOOP}" not in plan.resolved_path

    # =========================================================================
    # Case 7: Empty Definition (空定義)
    # =========================================================================
    def test_empty_blueprints(self, strategy: ExpansionStrategy, mock_parent):
        """
        [Edge Case] Blueprintリストが空の場合、エラーにならず空リストを返すこと。
        """
        parent = mock_parent(blueprints=[])
        plans = strategy.plan_next_nodes(parent, [])
        assert len(plans) == 0