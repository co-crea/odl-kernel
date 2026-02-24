import pytest
from odl_kernel.engine.logic.variable_resolver import VariableResolver
from odl_kernel.types import WiringObject

class TestVariableResolver:
    """
    [Unit Test] VariableResolver Logic

    Target:
        odl_kernel.engine.logic.variable_resolver.VariableResolver

    Responsibility:
        コンテキスト変数を用いて文字列内のトークン（{$LOOP}等）を解決する。
        算術演算（-1）を処理し、結果が0以下になる無効な参照を配線から除外する。
    """

    # =========================================================================
    # 1. Basic Substitution
    # =========================================================================
    def test_resolve_basic_variables(self):
        """[Happy Path] 単純な変数置換ができること"""
        context = {"$LOOP": 1, "$KEY": "user_id_123"}
        
        # 数値
        assert VariableResolver.resolve_string("Doc#v{$LOOP}", context) == "Doc#v1"
        # 文字列
        assert VariableResolver.resolve_string("Item_{$KEY}", context) == "Item_user_id_123"
        # 複数混在
        assert VariableResolver.resolve_string("path/{$KEY}/v{$LOOP}", context) == "path/user_id_123/v1"

    def test_keep_unresolved_variables(self):
        """[Soft Binding] コンテキストにない変数はそのまま残すこと"""
        context = {"$LOOP": 1}
        target = "Doc#v{$LOOP}_{$UNKNOWN}"
        
        resolved = VariableResolver.resolve_string(target, context)
        # $LOOPは解決されるが、$UNKNOWNはそのまま
        assert resolved == "Doc#v1_{$UNKNOWN}"

    # =========================================================================
    # 2. Arithmetic Operations
    # =========================================================================
    def test_resolve_arithmetic_expression(self):
        """[Math] {$LOOP-1} 等の算術演算ができること"""
        context = {"$LOOP": 5}
        
        # Subtraction
        assert VariableResolver.resolve_string("v{$LOOP-1}", context) == "v4"
        # Addition
        assert VariableResolver.resolve_string("v{$LOOP+1}", context) == "v6"
        # Zero padding (演算なし)
        assert VariableResolver.resolve_string("v{$LOOP}", context) == "v5"

    def test_resolve_nested_loop_variables(self):
        """[Nesting] {$LOOP^N} のような特殊な変数名も扱えること"""
        # $LOOP: Inner(2), $LOOP^1: Outer(1)
        context = {"$LOOP": 2, "$LOOP^1": 1}
        
        target = "Doc#parent_v{$LOOP^1}/child_v{$LOOP}"
        resolved = VariableResolver.resolve_string(target, context)
        
        assert resolved == "Doc#parent_v1/child_v2"

    # =========================================================================
    # 3. Filtering Logic (The Physics of Existence)
    # =========================================================================
    def test_resolve_wiring_filtering_zero_index(self):
        """
        [Filtering] 算術演算の結果が 0 以下になる参照は、配線リストから除外すること。
        Scenario: Loop Index = 1 (First iteration)
          - v{$LOOP}   -> v1 -> Keep
          - v{$LOOP-1} -> v0 -> Drop (存在しない過去)
        """
        context = {"$LOOP": 1}
        
        original_wiring = WiringObject(
            inputs=[
                "StaticDoc",          # No var -> Keep
                "PrevDoc#v{$LOOP-1}", # 1-1=0  -> Drop
                "CurrDoc#v{$LOOP}",   # 1      -> Keep
                "FutureDoc#v{$LOOP+1}"# 1+1=2  -> Keep (未来への参照はここではじかない)
            ],
            output="MyDoc#v{$LOOP}"
        )
        
        resolved_wiring = VariableResolver.resolve_wiring(original_wiring, context)
        
        inputs = resolved_wiring.inputs
        
        # 検証: v0 になる要素のみ消えていること
        assert len(inputs) == 3
        assert "StaticDoc" in inputs
        assert "PrevDoc#v0" not in inputs  # Dropped!
        assert "CurrDoc#v1" in inputs
        assert "FutureDoc#v2" in inputs

        # Outputは解決されること
        assert resolved_wiring.output == "MyDoc#v1"

    def test_resolve_wiring_filtering_negative_index(self):
        """[Filtering] 負の値になる場合も除外すること"""
        context = {"$LOOP": 1}
        # 1 - 2 = -1 -> Drop
        wiring = WiringObject(inputs=["DeepPast#v{$LOOP-2}"], output=None)
        
        resolved = VariableResolver.resolve_wiring(wiring, context)
        assert len(resolved.inputs) == 0

    def test_resolve_wiring_keep_string_vars(self):
        """[Edge Case] 文字列変数の場合はフィルタリングせず残すこと"""
        context = {"$KEY": "start"} 
        # 文字列に対する演算指定（通常ありえないが）は無視され、値がそのまま入る
        # "start" という文字列は有効な値として残る
        wiring = WiringObject(inputs=["Item#{$KEY}"], output=None)
        
        resolved = VariableResolver.resolve_wiring(wiring, context)
        assert resolved.inputs == ["Item#start"]