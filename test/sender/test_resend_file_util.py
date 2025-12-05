import os
import tempfile

from core.sender.legacy import resend_file_util


def test_when_extract_retry_count_then_return_expected_value():
    # Act & Assert
    assert resend_file_util.extract_retry_count("resend_20250903.json") == 0
    assert resend_file_util.extract_retry_count("resend_20250903.retry1.json") == 1
    assert resend_file_util.extract_retry_count("resend_20250903.retry3.json") == 3
    assert resend_file_util.extract_retry_count("invalid.retryX.json") == 0
    assert resend_file_util.extract_retry_count("resend_20250903.fail") == 0


def test_when_increment_retry_name_then_generate_next_filename():
    # Act & Assert
    assert resend_file_util.increment_retry_name("resend_20250903.json") == "resend_20250903.retry1.json"
    assert resend_file_util.increment_retry_name("resend_20250903.retry1.json") == "resend_20250903.retry2.json"
    assert resend_file_util.increment_retry_name("abc.retry3.json") == "abc.retry4.json"


def test_when_mark_as_fail_then_rename_file_and_preserve_content():
    # Arrange & Act
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a dummy retry file
        file_path = os.path.join(temp_dir, "resend_20250903.retry3.json")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("dummy")

        # Run mark_as_fail
        resend_file_util.mark_as_fail(file_path)

        # New path
        fail_path = os.path.join(temp_dir, "resend_20250903.fail")

        # Assert
        assert os.path.exists(fail_path)
        assert not os.path.exists(file_path)

        # Check content is preserved
        with open(fail_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert content == "dummy"
