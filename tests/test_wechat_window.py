import unittest

from summer_camp_agent.wechat_window import is_wechat_window_title


class WeChatWindowTest(unittest.TestCase):
    def test_accepts_wechat_titles(self):
        self.assertTrue(is_wechat_window_title("微信"))
        self.assertTrue(is_wechat_window_title("文件传输助手 - 微信"))
        self.assertTrue(is_wechat_window_title("沐曦开源英才夏令营咨询群 - 微信"))

    def test_rejects_non_wechat_titles(self):
        self.assertFalse(is_wechat_window_title(""))
        self.assertFalse(is_wechat_window_title("Visual Studio Code"))
        self.assertFalse(is_wechat_window_title("企业微信"))


if __name__ == "__main__":
    unittest.main()
