import pytest
import shutil
import sys
from pathlib import Path

# --- 修正: パス解決のハック ---
# この conftest.py があるディレクトリを sys.path に追加することで、
# 同階層にある harness.py を直接インポート可能にする
sys.path.append(str(Path(__file__).parent))

try:
    from harness import KernelSimulator
except ImportError:
    # パス追加が効いていない場合のフォールバック（通常はここには来ない）
    from .harness import KernelSimulator

@pytest.fixture(scope="session", autouse=True)
def clean_output_directories():
    """
    テストセッション開始時に、出力先ディレクトリ（logs, artifacts）を空にする
    """
    base_dir = Path(__file__).parent
    targets = ["logs", "artifacts"]

    for target_name in targets:
        target_dir = base_dir / target_name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(exist_ok=True)
        print(f"\n[Setup] Cleared directory: {target_dir}")

@pytest.fixture
def simulator_cls():
    """
    テストメソッドに対して KernelSimulator クラス自体を注入するフィクスチャ。
    相対インポート問題を回避し、テストコード側でのimport記述を不要にする。
    """
    return KernelSimulator