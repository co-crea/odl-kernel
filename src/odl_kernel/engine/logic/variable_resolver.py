# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

import re
from typing import Dict, Any, List, Optional
from odl_kernel.types import WiringObject

class VariableResolver:
    """
    [Physics Logic] Variable Resolver & Wiring Spreader

    Wiring（入出力配線）および文字列内の変数トークンを、実行時コンテキストに基づいて解決する。

    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic

    Physics Principles:
        1. Physics of Existence (存在の物理):
           以下の条件に該当する入力配線は「生存不能」とみなされ、配線リストから即座に除外（Filter out）される。
           - 変数がコンテキストに存在しない（例: 初回要素での $PREV）。
           - 算術演算の結果が 0 以下になる（例: v{$LOOP-1} where $LOOP=1）。
           - 解決を試みた結果、未解決のトークン `{$...}` が残留している。
        2. Spreading (リスト展開):
           変数がリスト型（例: $HISTORY）である場合、そのトークンを含む単一の入力定義を、
           リストの要素数に対応する複数の物理ID入力へと動的に展開する。
        3. Strict Token Boundary (厳格な境界):
           `{ }`（中括弧）で囲まれたもののみを解決対象とし、それ以外は固定の物理パスとして扱う。
    """

    # Regex for {$VAR}, {$VAR+N}, or {$VAR-N}
    # Group 1: Variable Name ($LOOP, $PREV, $HISTORY, $KEY等)
    # Group 2: Operator (+ or -)
    # Group 3: Operand (Integer)
    _TOKEN_PATTERN = re.compile(r'\{\s*(\$[\w\^]+)\s*(?:([\+\-])\s*(\d+))?\s*\}')

    @classmethod
    def resolve_wiring(cls, wiring: WiringObject, context: Dict[str, Any]) -> WiringObject:
        """
        WiringObject内の `inputs` および `output` を解決・展開する。

        Args:
            wiring (WiringObject): 解決前のWiring定義（IR由来）
            context (Dict[str, Any]): 現在の実行コンテキスト

        Returns:
            WiringObject: 解決・フィルタリング済みの物理配線
        """
        resolved_inputs: List[str] = []

        for original_input in wiring.inputs:
            # 1. Spreading Check (リスト展開の物理)
            # トークン内の変数がリスト型である場合、複数の物理IDに展開を試みる
            expanded_results = cls._expand_if_list(original_input, context)
            
            for item_string in expanded_results:
                # 2. Physics of Existence (生存判定)
                # 変数欠損や境界外参照を検知した場合、その配線は「なかったこと」にする
                if cls._is_invalid_reference(item_string, context):
                    continue

                # 3. String Resolution (最終置換)
                final_string = cls.resolve_string(item_string, context)

                # 最終チェック：未解決トークンが残っている場合は生存不能とみなす
                if "{$" not in final_string:
                    resolved_inputs.append(final_string)

        # Outputは解決のみ行う（自身の出力先名称であるため、フィルタリングは適用しない）
        resolved_output: Optional[str] = None
        if wiring.output:
            resolved_output = cls.resolve_string(wiring.output, context)

        return WiringObject(
            inputs=resolved_inputs,
            output=resolved_output
        )

    @classmethod
    def resolve_string(cls, text: str, context: Dict[str, Any]) -> str:
        """
        文字列内のトークンをコンテキストに基づいて置換する。

        Args:
            text (str): 置換対象の文字列
            context (Dict[str, Any]): 変数辞書

        Returns:
            str: 置換後の文字列。変数が未定義の場合は元のトークンを維持する（Soft Binding）。
        """
        if not text:
            return text

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            
            # 変数がコンテキストにない場合は置換せず、トークンのまま残す
            if var_name not in context:
                return match.group(0)

            operator = match.group(2)
            operand = int(match.group(3)) if match.group(3) else 0
            val = context[var_name]

            # 数値型の場合のみ演算を実行
            if isinstance(val, int):
                result = val
                if operator == '+': result += operand
                elif operator == '-': result -= operand
                return str(result)

            # 文字列（$KEY, $PREV等）の場合はそのままの値を文字列化して返す
            return str(val)

        return cls._TOKEN_PATTERN.sub(replacer, text)

    @classmethod
    def _expand_if_list(cls, text: str, context: Dict[str, Any]) -> List[str]:
        """
        [Physics] リスト型変数が含まれる場合、配線文字列を要素数分に展開する。
        
        Example:
            "Log#{$HISTORY}" + {$HISTORY: ["v1", "v2"]} 
            -> ["Log#v1", "Log#v2"]
        """
        match = cls._TOKEN_PATTERN.search(text)
        if not match:
            return [text]

        var_name = match.group(1)
        val = context.get(var_name)

        if isinstance(val, list):
            results = []
            prefix = text[:match.start()]
            suffix = text[match.end():]
            for item in val:
                # 各要素で置換された新しい文字列を生成
                results.append(f"{prefix}{item}{suffix}")
            return results
        
        return [text]

    @classmethod
    def _is_invalid_reference(cls, text: str, context: Dict[str, Any]) -> bool:
        """
        参照が物理的に無効（生存不能）かを判定する。

        判定基準:
            1. 変数欠損: トークン内の変数がコンテキストに存在しない場合（例: 初回の $PREV）。
            2. 境界外参照: 算術演算の結果が 0 以下になる場合（例: v{$LOOP-1} where $LOOP=1）。
        """
        for match in cls._TOKEN_PATTERN.finditer(text):
            var_name = match.group(1)
            
            # A. 変数自体が存在しない場合、この参照は無効（生存不能）
            if var_name not in context:
                return True

            # B. 算術演算の境界チェック
            operator = match.group(2)
            operand = int(match.group(3)) if match.group(3) else 0
            val = context[var_name]

            if isinstance(val, int):
                result = val
                if operator == '+': result += operand
                elif operator == '-': result -= operand

                # インデックスが 0 以下（存在しない過去）を指す場合は無効
                if result <= 0:
                    return True

        return False