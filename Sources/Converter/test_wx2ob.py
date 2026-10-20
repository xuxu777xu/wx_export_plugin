"""覆盖实测过的两种包（纯文字、带图片）和真实边界：同名图片、没被引用的附件、认不出格式的 TXT。

ZIP 按微信 4.1.13 实测结构构造：聊天记录.txt + 聊天记录内的图片、视频和文件/<附件>。
"""

import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import wx2ob as wx

MEDIA = "聊天记录内的图片、视频和文件/"
NOW = datetime(2026, 10, 4, 1, 0)  # noqa: DTZ001 与微信时间同为本地时间

# 格式取自 2026-10-04 实测转发的样本，内容是虚构的。
TEXT_ONLY = (
    "·小明\n2026年10月3日 12:05\n中午一起吃饭吗\n\n"
    "·小明\n2026年10月3日 12:38\n菜单：\n番茄炒蛋\n合计 | 2 人 36 元\n\n"
    "·小明\n2026年10月3日 18:45\n明天见\n"
)
WITH_IMAGE = (
    "·小明\n2026年10月3日 12:05\n看看这张图\n\n"
    "·小明\n2026年10月3日 13:22\n[图片] 微信图片_202610031322_1.jpg\n\n"
    "·小明\n2026年10月3日 13:22\n收到了吗\n"
)
IMAGE_NAME = "微信图片_202610031322_1.jpg"


def make_zip(
    folder: Path, name: str, transcript: str, files: dict[str, bytes] | None = None
) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("聊天记录.txt", transcript)
        for member, data in (files or {}).items():
            archive.writestr(MEDIA + member, data)
    return path


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.root = self.work / "wx"

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_only(self):
        note = wx.convert(make_zip(self.work, "Zip归档.zip", TEXT_ONLY), self.root, NOW)
        self.assertEqual(note.name, "小明 2026-10-03 1205-1845.md")
        content = note.read_text()
        self.assertIn("3 条", content)
        self.assertIn("## 2026-10-03", content)
        self.assertIn("**小明** 12:38", content)
        # 一条消息内的多行用行尾两个空格保住换行。
        self.assertIn("菜单：  \n番茄炒蛋  \n合计 | 2 人 36 元\n", content)
        self.assertFalse((self.root / "i").exists())

    def test_image_is_embedded_and_copied(self):
        zip_path = make_zip(
            self.work, "Zip归档.zip", WITH_IMAGE, {IMAGE_NAME: b"jpeg-1"}
        )
        content = wx.convert(zip_path, self.root, NOW).read_text()
        self.assertIn(f"![{IMAGE_NAME}](i/{IMAGE_NAME})", content)
        self.assertNotIn("[图片]", content)
        self.assertEqual((self.root / "i" / IMAGE_NAME).read_bytes(), b"jpeg-1")
        self.assertNotIn("其他附件", content)

    def test_same_name_image_reused_or_renamed(self):
        first = make_zip(self.work, "a.zip", WITH_IMAGE, {IMAGE_NAME: b"jpeg-1"})
        again = make_zip(self.work, "b.zip", WITH_IMAGE, {IMAGE_NAME: b"jpeg-1"})
        other = make_zip(self.work, "c.zip", WITH_IMAGE, {IMAGE_NAME: b"jpeg-2"})
        wx.convert(first, self.root, NOW)
        wx.convert(again, self.root, NOW)
        third = wx.convert(other, self.root, NOW).read_text()
        images = sorted(p.name for p in (self.root / "i").iterdir())
        self.assertEqual(images, [IMAGE_NAME, "微信图片_202610031322_1_2.jpg"])
        self.assertIn("(i/微信图片_202610031322_1_2.jpg)", third)
        # 同一段聊天导入三次，笔记不互相覆盖。
        notes = sorted(p.name for p in self.root.glob("*.md"))
        self.assertEqual(len(notes), 3)

    def test_unreferenced_attachment_listed(self):
        zip_path = make_zip(
            self.work, "z.zip", TEXT_ONLY, {"报价.pdf": b"%PDF", "x.mp4": b"v"}
        )
        content = wx.convert(zip_path, self.root, NOW).read_text()
        self.assertIn("## 其他附件", content)
        self.assertIn("- [报价.pdf](files/", content)
        self.assertIn("- [x.mp4](files/", content)
        self.assertTrue((self.root / "files" / "报价.pdf").exists())

    def test_link_path_escapes_only_link_breakers(self):
        self.assertEqual(wx.link_path("图 (1)%.jpg"), "图%20%281%29%25.jpg")

    def test_unparsed_transcript_kept_verbatim(self):
        note = wx.convert(
            make_zip(self.work, "z.zip", "随便一段\n# 不是聊天格式"), self.root, NOW
        )
        self.assertEqual(note.name, "微信聊天记录 2026-10-04 010000.md")
        self.assertIn("    # 不是聊天格式", note.read_text())

    def test_markdown_in_chat_is_escaped(self):
        transcript = "·a/b:c\n2026年10月3日 12:05\n# 不是标题\n1. 不是列表\n<b>x</b>\n"
        note = wx.convert(make_zip(self.work, "z.zip", transcript), self.root, NOW)
        self.assertEqual(note.name, "a_b_c 2026-10-03 1205-1205.md")
        content = note.read_text()
        self.assertIn("\\# 不是标题", content)
        self.assertIn("1\\. 不是列表", content)
        self.assertIn("\\<b>x\\</b>", content)

    def test_title_with_many_senders_and_days(self):
        transcript = (
            "·甲\n2026年10月3日 23:50\n1\n\n·乙\n2026年10月3日 23:55\n2\n\n"
            "·甲\n2026年10月4日 00:10\n3\n\n·丙\n2026年10月4日 00:20\n4\n"
        )
        note = wx.convert(make_zip(self.work, "z.zip", transcript), self.root, NOW)
        self.assertEqual(note.name, "甲、乙等3人 2026-10-03 2350 至 2026-10-04 0020.md")
        content = note.read_text()
        self.assertIn("## 2026-10-03", content)
        self.assertIn("## 2026-10-04", content)

    def test_main_skips_non_zip(self):
        bad = self.work / "x.txt"
        bad.write_text("x")
        good = make_zip(self.work, "Zip归档.zip", TEXT_ONLY)
        with mock.patch.dict(
            "os.environ", {"WX2OB_ROOT": str(self.root), "WX2OB_QUIET": "1"}
        ):
            code = wx.main([str(bad), str(good)])
        self.assertEqual(code, 1)
        self.assertEqual(len(list(self.root.glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
