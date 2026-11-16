"""Audio/video preview for macOS using the Qt Multimedia plugins shipped with PySide6."""

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget


class QtMediaPreviewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self.player.setAudioOutput(self._audio)
        self._video = QVideoWidget(self)
        self.player.setVideoOutput(self._video)
        self._status = QLabel(self)
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        self._play = QPushButton("播放", self)
        self._play.clicked.connect(self._toggle)
        self._seek = QSlider(Qt.Horizontal, self)
        self._seek.setAccessibleName("播放进度")
        self._seek.setRange(0, 0)
        self._seek.setEnabled(False)
        self._seek.valueChanged.connect(self.player.setPosition)
        controls = QHBoxLayout()
        controls.addWidget(self._play)
        controls.addWidget(self._seek, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self._video, 1)
        layout.addWidget(self._status)
        layout.addLayout(controls)
        toggle = QShortcut(QKeySequence(Qt.Key_Space), self)
        toggle.setContext(Qt.WidgetWithChildrenShortcut)
        toggle.activated.connect(self._toggle)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.seekableChanged.connect(self._seek.setEnabled)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.errorOccurred.connect(self._error)

    def set_file(self, file_path: str, is_audio: bool = False):
        self.player.stop()
        self._status.setText(Path(file_path).name)
        self._video.setVisible(not is_audio)
        self._play.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.player.play()

    def _duration_changed(self, duration):
        self._seek.setMaximum(min(duration, 2**31 - 1))

    def _position_changed(self, position):
        if not self._seek.isSliderDown():
            with QSignalBlocker(self._seek):
                self._seek.setValue(min(position, self._seek.maximum()))

    def _toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _state_changed(self, state):
        self._play.setText("暂停" if state == QMediaPlayer.PlayingState else "播放")

    def _error(self, _error, description):
        self._status.setText(f"无法播放：{description}")
        self._play.setEnabled(False)

    def stop_playback(self):
        self.player.stop()
        self.player.setSource(QUrl())
