import unittest

import torch

from app.main import _global_pca, _local_pca, _matrix, _numbers, _prediction_rows, _sample


class FakeTokenizer:
    def decode(self, token_ids):
        return f"token-{token_ids[0]}"


class TensorSerializerTest(unittest.TestCase):
    def test_tensor_serializers_are_stable_and_rounded(self):
        tensor = torch.tensor([[1.0, 1.0 / 3.0], [-0.0, 4.0]])

        self.assertEqual(_numbers(tensor[0]), [1.0, 0.3333333])
        self.assertEqual(_matrix(tensor), [[1.0, 0.3333333], [-0.0, 4.0]])
        self.assertEqual(_sample(tensor[0], torch.tensor([1])), [0.3333333])

    def test_prediction_rows_are_ranked_from_logits(self):
        rows = _prediction_rows(FakeTokenizer(), torch.tensor([0.1, 2.0, 0.5]), count=2)

        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual([row["rank"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["token"], "token-1")
        self.assertGreater(rows[0]["probability"], rows[1]["probability"])

    def test_local_pca_returns_three_bounded_coordinates(self):
        vectors = torch.arange(40, dtype=torch.float32).reshape(5, 8)
        coordinates = _local_pca(vectors)

        self.assertEqual(tuple(coordinates.shape), (5, 3))
        self.assertLessEqual(float(coordinates.abs().max()), 1.0)
        self.assertTrue(torch.allclose(coordinates.mean(dim=0), torch.zeros(3), atol=1e-5))

    def test_global_pca_returns_three_robustly_scaled_coordinates(self):
        vectors = torch.arange(80, dtype=torch.float32).reshape(10, 8)
        coordinates = _global_pca(vectors)

        self.assertEqual(tuple(coordinates.shape), (10, 3))
        self.assertLessEqual(float(coordinates.abs().max()), 1.25)
        self.assertTrue(torch.allclose(coordinates.mean(dim=0), torch.zeros(3), atol=1e-5))


if __name__ == "__main__":
    unittest.main()
