"""
Test regression log lifecycle: clear on fresh start, save copy to output
"""
import sys
from pathlib import Path
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.regression_log import (
    RegressionLog,
    RegressionLogEntry,
    VerificationResult,
    ImpactAnalysis
)


def test_clear_on_fresh_start():
    """Test that regression log clears on fresh start."""
    print("=" * 80)
    print("TEST 1: Clear Regression Log on Fresh Start")
    print("=" * 80)

    # Create temporary directory for test
    temp_dir = Path(tempfile.mkdtemp())
    log_file = temp_dir / "regression_log.json"

    try:
        # Create a regression log with some entries
        reg_log = RegressionLog(log_path=log_file)
        reg_log.add_entry(RegressionLogEntry(
            iteration_id=1,
            model_file_location="test.als",
            fix_intent="Test fix 1",
            source_ref="Test source",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis()
        ))
        reg_log.add_entry(RegressionLogEntry(
            iteration_id=2,
            model_file_location="test.als",
            fix_intent="Test fix 2",
            source_ref="Test source",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis()
        ))

        print(f"\nCreated regression log with {len(reg_log.entries)} entries")
        assert len(reg_log.entries) == 2, "Should have 2 entries"
        assert log_file.exists(), "Log file should exist"

        # Simulate fresh start - clear the log
        print("\nSimulating fresh start (iteration 0)...")
        reg_log.clear()

        print(f"After clear: {len(reg_log.entries)} entries")
        assert len(reg_log.entries) == 0, "Should have 0 entries after clear"
        assert not log_file.exists(), "Log file should be deleted after clear"

        print("\n  ✅ Clear on fresh start working correctly")

    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


def test_trim_on_resume():
    """Test that regression log trims to target iteration on resume."""
    print("\n" + "=" * 80)
    print("TEST 2: Trim Regression Log on Resume")
    print("=" * 80)

    # Create temporary directory for test
    temp_dir = Path(tempfile.mkdtemp())
    log_file = temp_dir / "regression_log.json"

    try:
        # Create a regression log with entries from iterations 1-5
        reg_log = RegressionLog(log_path=log_file)
        for i in range(1, 6):
            reg_log.add_entry(RegressionLogEntry(
                iteration_id=i,
                model_file_location=f"test_{i}.als",
                fix_intent=f"Test fix {i}",
                source_ref="Test source",
                current_result=VerificationResult(syntax="Error"),
                previous_result=None,
                updated_lines="",
                expected_impact=ImpactAnalysis()
            ))

        print(f"\nCreated regression log with {len(reg_log.entries)} entries (iterations 1-5)")
        assert len(reg_log.entries) == 5, "Should have 5 entries"

        # Simulate resume from iteration 3
        print("\nSimulating resume from iteration 3...")
        print("  (Should keep entries 1-2, remove entries 3-5)")
        reg_log.trim_to_iteration(3)

        print(f"After trim to iteration 3: {len(reg_log.entries)} entries")
        assert len(reg_log.entries) == 2, "Should have 2 entries after trim to iteration 3"

        # Verify correct entries remain
        remaining_ids = [e.iteration_id for e in reg_log.entries]
        print(f"Remaining iterations: {remaining_ids}")
        assert remaining_ids == [1, 2], "Should only have iterations 1 and 2"

        print("\n  ✅ Trim on resume working correctly")

    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


def test_persistence_after_clear():
    """Test that clear actually deletes the file and new log starts fresh."""
    print("\n" + "=" * 80)
    print("TEST 3: Persistence After Clear")
    print("=" * 80)

    # Create temporary directory for test
    temp_dir = Path(tempfile.mkdtemp())
    log_file = temp_dir / "regression_log.json"

    try:
        # Create and populate a log
        reg_log1 = RegressionLog(log_path=log_file)
        reg_log1.add_entry(RegressionLogEntry(
            iteration_id=1,
            model_file_location="test.als",
            fix_intent="Old entry",
            source_ref="Test source",
            current_result=VerificationResult(syntax="Error"),
            previous_result=None,
            updated_lines="",
            expected_impact=ImpactAnalysis()
        ))

        print(f"\nLog 1: {len(reg_log1.entries)} entries")
        assert len(reg_log1.entries) == 1

        # Clear it
        reg_log1.clear()
        print("Log 1 cleared")

        # Create a new RegressionLog instance (simulating new workflow run)
        print("\nCreating new RegressionLog instance (simulating new workflow)...")
        reg_log2 = RegressionLog(log_path=log_file)

        print(f"Log 2: {len(reg_log2.entries)} entries")
        assert len(reg_log2.entries) == 0, "New log should start with 0 entries after clear"

        print("\n  ✅ Persistence after clear working correctly")

    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


def test_trim_boundary_cases():
    """Test trim behavior with boundary cases."""
    print("\n" + "=" * 80)
    print("TEST 4: Trim Boundary Cases")
    print("=" * 80)

    temp_dir = Path(tempfile.mkdtemp())
    log_file = temp_dir / "regression_log.json"

    try:
        # Create log with iterations 1-5
        reg_log = RegressionLog(log_path=log_file)
        for i in range(1, 6):
            reg_log.add_entry(RegressionLogEntry(
                iteration_id=i,
                model_file_location=f"test_{i}.als",
                fix_intent=f"Fix {i}",
                source_ref="Test",
                current_result=VerificationResult(syntax="OK"),
                previous_result=None,
                updated_lines="",
                expected_impact=ImpactAnalysis()
            ))

        # Test trim to iteration 1 (should remove all)
        print("\nTest: Trim to iteration 1 (should keep nothing)")
        reg_log.trim_to_iteration(1)
        assert len(reg_log.entries) == 0, "Trim to 1 should keep no entries"
        print("  ✓ Trim to iteration 1: 0 entries remaining")

        # Recreate log
        for i in range(1, 6):
            reg_log.add_entry(RegressionLogEntry(
                iteration_id=i,
                model_file_location=f"test_{i}.als",
                fix_intent=f"Fix {i}",
                source_ref="Test",
                current_result=VerificationResult(syntax="OK"),
                previous_result=None,
                updated_lines="",
                expected_impact=ImpactAnalysis()
            ))

        # Test trim to iteration 10 (beyond range, should keep all)
        print("\nTest: Trim to iteration 10 (beyond range, should keep all)")
        reg_log.trim_to_iteration(10)
        assert len(reg_log.entries) == 5, "Trim to 10 should keep all 5 entries"
        print("  ✓ Trim to iteration 10: 5 entries remaining")

        print("\n  ✅ Boundary cases working correctly")

    finally:
        shutil.rmtree(temp_dir)


def test_save_copy_to_output():
    """Test saving a copy of regression log to Output directory."""
    print("\n" + "=" * 80)
    print("TEST 5: Save Copy to Output Directory")
    print("=" * 80)

    temp_dir = Path(tempfile.mkdtemp())
    log_file = temp_dir / "regression_log.json"
    output_dir = temp_dir / "Output" / "RegressionLog"

    try:
        # Create log with entries
        reg_log = RegressionLog(log_path=log_file)
        for i in range(1, 4):
            reg_log.add_entry(RegressionLogEntry(
                iteration_id=i,
                model_file_location=f"test_{i}.als",
                fix_intent=f"Fix {i}",
                source_ref="Test",
                current_result=VerificationResult(syntax="OK"),
                previous_result=None,
                updated_lines="",
                expected_impact=ImpactAnalysis()
            ))

        print(f"\nCreated regression log with {len(reg_log.entries)} entries")

        # Save copy to output
        print("\nSaving copy to Output/RegressionLog/...")
        reg_log.save_copy_to_output(output_dir)

        # Verify copy was created
        saved_files = list(output_dir.glob("regression*.log"))
        assert len(saved_files) > 0, "Should have created a copy in Output/RegressionLog/"

        saved_file = saved_files[0]
        print(f"✓ Copy saved: {saved_file.name}")

        # Verify filename format (regressionMMDD_HHAM/PM.log)
        import re
        pattern = r"regression\d{4}_\d{2}(AM|PM)\.log"
        assert re.match(pattern, saved_file.name), f"Filename should match format regressionMMDD_HHAM/PM.log, got {saved_file.name}"
        print(f"✓ Filename format correct: {saved_file.name}")

        # Verify content is preserved
        import json
        with open(saved_file) as f:
            data = json.load(f)
        assert len(data) == 3, "Copy should have all 3 entries"
        print(f"✓ All {len(data)} entries preserved in copy")

        # Test that copy persists even after clearing memory log
        print("\nClearing memory log...")
        reg_log.clear()
        assert len(reg_log.entries) == 0, "Memory log should be cleared"
        assert not log_file.exists(), "Memory log file should be deleted"

        # Verify copy still exists
        assert saved_file.exists(), "Output copy should still exist"
        print("✓ Output copy persists after memory log cleared")

        print("\n  ✅ Save copy to output working correctly")

    finally:
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("TESTING REGRESSION LOG LIFECYCLE")
    print("=" * 80 + "\n")

    try:
        test_clear_on_fresh_start()
        test_trim_on_resume()
        test_persistence_after_clear()
        test_trim_boundary_cases()
        test_save_copy_to_output()

        print("\n" + "=" * 80)
        print("✅ ALL LIFECYCLE TESTS PASSED!")
        print("=" * 80 + "\n")

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80 + "\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
