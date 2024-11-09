from vosk import Model, SpkModel, KaldiRecognizer


class BuscribeRecognizer:
    segments_start_time = None

    def __init__(self, sample_rate=48000, model_path="model_small", spk_model_path="spk_model"):
        """Loads the speech recognition model and initializes the recognizer.

        Model paths are file paths to the directories that contain the models.

        Returns a recognizer object.
        """
        self.sample_rate = sample_rate
        self.model = Model(model_path)
        self.spk_model = SpkModel(spk_model_path)

        self.recognizer = KaldiRecognizer(self.model, self.sample_rate, self.spk_model)
        self.recognizer.SetWords(True)

    def reset(self):
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate, self.spk_model)
        self.recognizer.SetWords(True)
        self.segments_start_time = None

    def accept_waveform(self, data):
        return self.recognizer.AcceptWaveform(data)

    def result(self):
        return self.recognizer.Result()

    def final_result(self):
        return self.recognizer.FinalResult()
