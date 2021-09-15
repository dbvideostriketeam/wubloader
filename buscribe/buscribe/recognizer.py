from vosk import Model, SpkModel, KaldiRecognizer


class BuscribeRecognizer(KaldiRecognizer):
    segments_start_time = None

    def __init__(self, sample_rate=48000, model_path="model_small", spk_model_path="spk_model"):
        """Loads the speech recognition model and initializes the recognizer.

        Model paths are file paths to the directories that contain the models.

        Returns a recognizer object.
        """
        self.model = Model(model_path)
        self.spk_model = SpkModel(spk_model_path)

        super(BuscribeRecognizer, self).__init__(self.model, sample_rate, self.spk_model)

        self.SetWords(True)

    def Reset(self):
        super(BuscribeRecognizer, self).Reset()
        self.segments_start_time = None
