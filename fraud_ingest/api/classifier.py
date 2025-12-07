class AnomalyToClassifier:
    def __init__(self, model, threshold=0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        self.model.learn_one(x)
        return self

    def predict_proba_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)

        return {0: 1 - score, 1: score}

    def predict_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)
