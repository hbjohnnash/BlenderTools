"""Tests for animation.ml.bvh_utils — BVH file parsing.

The BVH parser is pure Python (reads text, returns dicts) so it
runs without Blender. We test it with the sample BVH file from conftest.
"""

from animation.ml.bvh_utils import parse_bvh


class TestParseBvhHierarchy:
    """Test that the hierarchy section is parsed correctly."""

    def test_finds_all_joints(self, sample_bvh_file):
        """Should find ROOT + 2 JOINTs = 3 joints total."""
        result = parse_bvh(sample_bvh_file)
        names = [j["name"] for j in result["joints"]]
        assert names == ["Hips", "Spine", "Head"]

    def test_root_has_no_parent(self, sample_bvh_file):
        result = parse_bvh(sample_bvh_file)
        root = result["joints"][0]
        assert root["name"] == "Hips"
        assert root["parent"] is None

    def test_child_parent_links(self, sample_bvh_file):
        """Spine's parent should be 'Hips', Head's parent should be 'Spine'."""
        result = parse_bvh(sample_bvh_file)
        joints = result["joints"]
        spine = joints[1]
        head = joints[2]
        assert spine["parent"] == "Hips"
        assert head["parent"] == "Spine"

    def test_joint_offsets(self, sample_bvh_file):
        """Offsets should match what's in the BVH file."""
        result = parse_bvh(sample_bvh_file)
        hips_offset = result["joints"][0]["offset"]
        spine_offset = result["joints"][1]["offset"]
        assert hips_offset == (0.0, 0.0, 0.0)
        assert spine_offset == (0.0, 5.0, 0.0)

    def test_root_has_6_channels(self, sample_bvh_file):
        """Root joint should have 6 channels (position + rotation)."""
        result = parse_bvh(sample_bvh_file)
        root = result["joints"][0]
        assert len(root["channels"]) == 6

    def test_child_has_3_channels(self, sample_bvh_file):
        """Non-root joints should have 3 channels (rotation only)."""
        result = parse_bvh(sample_bvh_file)
        spine = result["joints"][1]
        assert len(spine["channels"]) == 3


class TestParseBvhMotion:
    """Test that the motion data section is parsed correctly."""

    def test_frame_count(self, sample_bvh_file):
        """Should find exactly 3 frames of motion data."""
        result = parse_bvh(sample_bvh_file)
        assert len(result["frames"]) == 3

    def test_frame_time(self, sample_bvh_file):
        result = parse_bvh(sample_bvh_file)
        assert abs(result["frame_time"] - 0.033333) < 0.001

    def test_values_per_frame(self, sample_bvh_file):
        """Each frame should have 12 values (6 root + 3 spine + 3 head)."""
        result = parse_bvh(sample_bvh_file)
        for frame in result["frames"]:
            assert len(frame) == 12

    def test_first_frame_values(self, sample_bvh_file):
        """Spot-check specific values from frame 0."""
        result = parse_bvh(sample_bvh_file)
        frame0 = result["frames"][0]
        # Root Xposition = 0.0, Yposition = 1.0
        assert frame0[0] == 0.0
        assert frame0[1] == 1.0
        # Spine Xrotation = 10.0 (second channel of Spine)
        assert frame0[7] == 10.0

    def test_channel_offsets_are_correct(self, sample_bvh_file):
        """Channel offsets should let us index into frame data correctly."""
        result = parse_bvh(sample_bvh_file)
        joints = result["joints"]
        # Hips: offset 0, 6 channels
        assert joints[0]["channel_offset"] == 0
        # Spine: offset 6, 3 channels
        assert joints[1]["channel_offset"] == 6
        # Head: offset 9, 3 channels
        assert joints[2]["channel_offset"] == 9


class TestParseBvhEdgeCases:
    """Test parser robustness with unusual input."""

    def test_empty_motion(self, tmp_path):
        """BVH with zero frames should parse without crashing."""
        bvh = tmp_path / "empty.bvh"
        bvh.write_text("""\
HIERARCHY
ROOT Bone
{
  OFFSET 0.0 0.0 0.0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  End Site
  {
    OFFSET 0.0 1.0 0.0
  }
}
MOTION
Frames: 0
Frame Time: 0.033333
""", encoding="utf-8")
        result = parse_bvh(bvh)
        assert len(result["joints"]) == 1
        assert len(result["frames"]) == 0

    def test_single_bone_skeleton(self, tmp_path):
        """A skeleton with just a root and end site should parse."""
        bvh = tmp_path / "single.bvh"
        bvh.write_text("""\
HIERARCHY
ROOT Root
{
  OFFSET 0.0 0.0 0.0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  End Site
  {
    OFFSET 0.0 1.0 0.0
  }
}
MOTION
Frames: 1
Frame Time: 0.041667
1.0 2.0 3.0 45.0 0.0 0.0
""", encoding="utf-8")
        result = parse_bvh(bvh)
        assert len(result["joints"]) == 1
        assert result["joints"][0]["name"] == "Root"
        assert result["frames"][0][3] == 45.0
