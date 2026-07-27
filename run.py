import unittest


class MyTestCase(unittest.TestCase):
    def test_something(self):
        data = "/projects/BH/repos/webapp-ui/pull-requests/414/diff"
        data = data.split("/")
        pr_id = f"{data[2]}__{data[4]}__{data[6]}"
        self.assertEqual(pr_id, "BH__webapp-ui__414")


if __name__ == '__main__':
    unittest.main()
