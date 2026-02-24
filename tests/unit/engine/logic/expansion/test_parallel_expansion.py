import pytest
from uuid import uuid4
from typing import List

from odl_kernel.types import IrComponent, OpCode, NodeType, WiringObject, ProcessNode, LifecycleStatus, BusinessResult

# Target Strategy
from odl_kernel.engine.logic.expansion.base import ExpansionStrategy
from odl_kernel.engine.logic.expansion.parallel import ParallelExpansionStrategy

class TestParallelExpansionStrategy:
    
    @pytest.fixture
    def strategy(self) -> ExpansionStrategy:
        return ParallelExpansionStrategy()

    @pytest.fixture
    def mock_parent(self):
        """
        Parallelの親ノードを生成するヘルパー。
        stack_path (親の物理パス) を指定可能にする。
        """
        def _create(blueprints: List[IrComponent], path: str = "root/parallel_0") -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.CONTROL,
                opcode=OpCode.PARALLEL,
                stack_path=path,
                wiring=WiringObject(inputs=[], output=None),
                children_blueprint=blueprints,
                params={}
            )
        return _create

    @pytest.fixture
    def mock_child(self):
        """
        指定したパスを持つ子ノードを生成するヘルパー。
        """
        def _create(path: str, status: LifecycleStatus = LifecycleStatus.PENDING) -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.ACTION,
                opcode=OpCode.WORKER,
                stack_path=path,
                wiring=WiringObject(inputs=[], output=None),
                lifecycle_status=status
            )
        return _create

    # =========================================================================
    # Case 1: Batch Creation (完全新規作成)
    # =========================================================================
    def test_batch_creation(self, strategy: ExpansionStrategy, mock_parent):
        """
        [Happy Path] 子ノードが一つもない時、全てのBlueprintに対する計画を一括で立てること。
        各計画の original_index がリスト順と一致していることを確認する。
        """
        bp1 = IrComponent(stack_path="root/parallel_0/worker_1", opcode=OpCode.WORKER)
        bp2 = IrComponent(stack_path="root/parallel_0/worker_2", opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp1, bp2], path="root/parallel_0")
        
        plans = strategy.plan_next_nodes(parent, [])

        assert len(plans) == 2
        
        # 順不同可だが、検証のためパスでソートして確認
        # (実装上はリスト順に追加されるため、そのままアクセスしても良いが、堅牢に検証する)
        sorted_plans = sorted(plans, key=lambda p: p.original_index)
        
        # 1つ目
        assert sorted_plans[0].blueprint == bp1
        assert sorted_plans[0].resolved_path == "root/parallel_0/worker_1"
        assert sorted_plans[0].original_index == 0
        assert sorted_plans[0].context_vars == {}
        
        # 2つ目
        assert sorted_plans[1].blueprint == bp2
        assert sorted_plans[1].resolved_path == "root/parallel_0/worker_2"
        assert sorted_plans[1].original_index == 1
        assert sorted_plans[1].context_vars == {}

    # =========================================================================
    # Case 2: Idempotency (冪等性 - 全て存在する場合)
    # =========================================================================
    def test_idempotency_all_exists(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Stability] 定義された全ての子ノードが既に存在する場合、何も計画しないこと。
        子のStatusがFAILEDであっても「存在する」事実は変わらないため、再生成しない。
        """
        bp1 = IrComponent(stack_path="root/p/worker_1", opcode=OpCode.WORKER)
        parent = mock_parent(blueprints=[bp1], path="root/p")
        
        # 子が存在する (FAILED状態)
        child1 = mock_child(path="root/p/worker_1", status=LifecycleStatus.FAILED)
        
        plans = strategy.plan_next_nodes(parent, [child1])

        assert len(plans) == 0

    # =========================================================================
    # Case 3: Partial Recovery (欠損の修復 - 重要)
    # =========================================================================
    def test_partial_recovery_with_correct_index(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Resilience] 一部の子ノードが欠落している場合、その差分のみを計画すること。
        【最重要】生成される計画の original_index が「生成リスト上の連番」ではなく、
        「親Blueprintリスト上の絶対位置」を正しく指していることを検証する。
        """
        # 定義: A(idx=0), B(idx=1), C(idx=2)
        bp_a = IrComponent(stack_path="root/p/A", opcode=OpCode.WORKER)
        bp_b = IrComponent(stack_path="root/p/B", opcode=OpCode.WORKER)
        bp_c = IrComponent(stack_path="root/p/C", opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp_a, bp_b, bp_c], path="root/p")
        
        # 現状: AとCは存在する (Bが欠損)
        child_a = mock_child(path="root/p/A")
        child_c = mock_child(path="root/p/C")
        
        plans = strategy.plan_next_nodes(parent, [child_a, child_c])

        # 期待値: Bだけが計画される
        assert len(plans) == 1
        plan = plans[0]
        
        assert plan.blueprint == bp_b
        assert plan.resolved_path == "root/p/B"
        
        # Check Index: 真ん中の定義なので 1 (0-based) であるべき
        # もし単なる append なら 0 になってしまうが、enumerate を使っていれば 1 になる
        assert plan.original_index == 1

    # =========================================================================
    # Case 4: Nested Path Resolution (ネスト時の動的パス解決)
    # =========================================================================
    def test_nested_path_resolution(self, strategy: ExpansionStrategy, mock_parent):
        """
        [Critical] 親がLoop/Iterate内などで動的パス(v2)を持っている場合、
        Blueprintにトークン($LOOP)が含まれていても、親パスを正しく継承すること。
        """
        # 親: Loop(v2) 内の Parallel
        parent_path = "root/loop_0/v2/parallel_inner"
        
        # Blueprint: コンパイラ出力の絶対パス (未解決トークンを含む)
        tokenized_path = "root/loop_0/v{$LOOP}/parallel_inner/worker_X"
        bp = IrComponent(stack_path=tokenized_path, opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprints=[bp], path=parent_path)
        
        plans = strategy.plan_next_nodes(parent, [])

        assert len(plans) == 1
        
        # 検証: 親パス(v2) + ノード名(worker_X)
        expected_path = "root/loop_0/v2/parallel_inner/worker_X"
        assert plans[0].resolved_path == expected_path
        
        # {$LOOP} が残っていないことを保証
        assert "{$LOOP}" not in plans[0].resolved_path

    # =========================================================================
    # Case 5: Extra Children (未知の子供 - 耐障害性)
    # =========================================================================
    def test_ignore_extra_children(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [Robustness] 定義にない未知の子供（古いバージョンの残骸やバグによる生成物）が存在しても、
        正規の定義(Blueprint)の欠損判定ロジックを阻害しないこと。
        """
        bp1 = IrComponent(stack_path="root/p/worker_1", opcode=OpCode.WORKER)
        parent = mock_parent(blueprints=[bp1], path="root/p")
        
        # 定義にない謎の子供 (worker_ghost)
        ghost_child = mock_child(path="root/p/worker_ghost")
        
        # worker_1 は欠損している -> 生成すべき
        plans = strategy.plan_next_nodes(parent, [ghost_child])

        assert len(plans) == 1
        assert plans[0].resolved_path == "root/p/worker_1"
        assert plans[0].original_index == 0

    # =========================================================================
    # Case 6: Empty Blueprints (空定義)
    # =========================================================================
    def test_empty_blueprints(self, strategy: ExpansionStrategy, mock_parent):
        """Blueprintが空の場合は何も計画しないこと"""
        parent = mock_parent(blueprints=[], path="root/p")
        plans = strategy.plan_next_nodes(parent, [])
        assert len(plans) == 0