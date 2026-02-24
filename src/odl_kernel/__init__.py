# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from .types import (
    JobSnapshot, 
    KernelEvent, 
    AnalysisResult
)
from .engine.analyzer import OdlAnalyzer
from .engine.logic.introspection import NodeInspector

# Main Entry Point
def analyze(snapshot: JobSnapshot, event: KernelEvent) -> AnalysisResult:
    """
    ODLカーネルのメインエントリポイント。
    物理法則に基づき、入力されたSnapshotとEventから次のアクションを導出する純粋関数。
    
    Usage:
        import odl_kernel
        result = odl_kernel.analyze(snapshot, event)
    
    Args:
        snapshot: 現在のジョブの状態 (DBからロード済み)
        event: トリガーとなった事象 (Tick, ActionCompleted等)
        
    Returns:
        AnalysisResult: 実行すべきコマンドと、更新されたノード状態
    """
    # Analyzerはステートレスなので、都度インスタンス化して実行する
    # これにより odl.compile(...) と同じような関数的な使い心地を提供する
    return OdlAnalyzer().analyze(snapshot, event)

__all__ = [
    "analyze",
    "JobSnapshot",
    "KernelEvent", 
    "AnalysisResult",
    "NodeInspector"
]