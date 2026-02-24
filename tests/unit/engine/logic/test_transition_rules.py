import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from odl_kernel.types import (
    ProcessNode,
    LifecycleStatus, 
    BusinessResult, 
    CommandType,
    OpCode, 
    NodeType, 
    WiringObject,
    ContextSchema
)
from odl_kernel.engine.logic.transition_rules import TransitionRules


class TestTransitionRules:
    """
    [Unit Test] TransitionRules Logic
    
    Target:
        odl_kernel.engine.logic.transition_rules.TransitionRules
        
    Responsibility:
        ノードと子ノードの状態から、次に発生すべき遷移コマンド（TRANSITION/FINALIZE）を決定論的に導出する。
    """

    @pytest.fixture
    def mock_node(self):
        def _create(
            status=LifecycleStatus.RUNNING, 
            opcode=OpCode.SERIAL, 
            output=None, 
            result=BusinessResult.SUCCESS, 
            timeout_at=None
        ):
            # Output Aggregationのモック (完了済みノードが成果物を持っている状態)
            ctx = ContextSchema()
            if output is not None:
                ctx.output_aggregation = [output]

            return ProcessNode(
                node_id=uuid4().hex,
                stack_path="root/test",
                node_type=NodeType.CONTROL if opcode != OpCode.WORKER else NodeType.ACTION,
                opcode=opcode,
                wiring=WiringObject(inputs=[], output=None),
                lifecycle_status=status,
                business_result=result,
                timeout_at=timeout_at,
                runtime_context=ctx
            )
        return _create

    # =========================================================================
    # 1. Wake Up Logic (Pending -> Running)
    # =========================================================================
    def test_wakeup_control_node(self, mock_node):
        """[Rule] Controlノードは生成直後(PENDING)にRUNNINGへ遷移すべき"""
        node = mock_node(status=LifecycleStatus.PENDING, opcode=OpCode.SERIAL)
        cmd = TransitionRules.evaluate(node, [], datetime.now())
        
        assert cmd is not None
        assert cmd.type == CommandType.TRANSITION
        assert cmd.payload["to_status"] == LifecycleStatus.RUNNING

    def test_ignore_pending_action_node(self, mock_node):
        """[Rule] ActionノードのPENDING->RUNNINGは外部Dispatchで行うため、ここでは何もしない"""
        node = mock_node(status=LifecycleStatus.PENDING, opcode=OpCode.WORKER)
        cmd = TransitionRules.evaluate(node, [], datetime.now())
        assert cmd is None

    # =========================================================================
    # 2. Timeout (Zombie Killer)
    # =========================================================================
    def test_timeout_detection(self, mock_node):
        """[Rule] タイムアウト時刻を過ぎたRUNNINGノードはFAILEDへ"""
        now = datetime.now()
        past = (now - timedelta(seconds=1)).timestamp()
        
        node = mock_node(timeout_at=past)
        cmd = TransitionRules.evaluate(node, [], now)
        
        assert cmd.type == CommandType.TRANSITION
        assert cmd.payload["to_status"] == LifecycleStatus.FAILED
        assert cmd.payload["reason"] == "E_EXECUTION_TIMEOUT"

    # =========================================================================
    # 3. Failure Propagation
    # =========================================================================
    def test_serial_fail_fast(self, mock_node):
        """[Rule] Serial: 子が1つでもFAILEDなら即座に親もFAILED (Fail Fast)"""
        parent = mock_node(opcode=OpCode.SERIAL)
        children = [
            mock_node(status=LifecycleStatus.COMPLETED),
            mock_node(status=LifecycleStatus.FAILED), # Failure
            mock_node(status=LifecycleStatus.PENDING)
        ]
        cmd = TransitionRules.evaluate(parent, children, datetime.now())
        
        assert cmd.type == CommandType.TRANSITION
        assert cmd.payload["to_status"] == LifecycleStatus.FAILED

    def test_parallel_graceful_wait(self, mock_node):
        """[Rule] Parallel: 子がFAILEDでも、他の兄弟が動いていれば待つ (Graceful Wait)"""
        parent = mock_node(opcode=OpCode.PARALLEL)
        children = [
            mock_node(status=LifecycleStatus.FAILED),
            mock_node(status=LifecycleStatus.RUNNING) # Still active
        ]
        cmd = TransitionRules.evaluate(parent, children, datetime.now())
        assert cmd is None

    # =========================================================================
    # 4. Completion & Aggregation
    # =========================================================================
    def test_all_completed_success(self, mock_node):
        """[Rule] 全ての子が完了すれば、親もFINALIZEされる"""
        parent = mock_node(opcode=OpCode.SERIAL)
        children = [
            mock_node(status=LifecycleStatus.COMPLETED, result=BusinessResult.SUCCESS),
            mock_node(status=LifecycleStatus.COMPLETED, result=BusinessResult.SUCCESS)
        ]
        cmd = TransitionRules.evaluate(parent, children, datetime.now())
        
        assert cmd.type == CommandType.FINALIZE
        assert cmd.payload["result"] == BusinessResult.SUCCESS

    def test_output_aggregation_serial(self, mock_node):
        """[Rule] Serial Aggregation: 最後の子の出力を採用する"""
        parent = mock_node(opcode=OpCode.SERIAL)
        children = [
            mock_node(status=LifecycleStatus.COMPLETED, output="out_1"),
            mock_node(status=LifecycleStatus.COMPLETED, output="out_2")
        ]
        cmd = TransitionRules.evaluate(parent, children, datetime.now())
        
        assert cmd.payload["output_data"] == "out_2"

    def test_output_aggregation_parallel(self, mock_node):
        """[Rule] Parallel Aggregation: 全ての子の出力をリスト化する"""
        parent = mock_node(opcode=OpCode.PARALLEL)
        children = [
            mock_node(status=LifecycleStatus.COMPLETED, output="out_A"),
            mock_node(status=LifecycleStatus.COMPLETED, output="out_B")
        ]
        cmd = TransitionRules.evaluate(parent, children, datetime.now())
        
        data = cmd.payload["output_data"]
        assert isinstance(data, list)
        assert data == ["out_A", "out_B"]