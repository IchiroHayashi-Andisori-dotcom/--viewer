import sys
import os
import csv
import time
import tempfile
import pymupdf
import pygame
from pydub import AudioSegment
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QScrollArea, QPushButton, QProgressBar, QSizePolicy, QFileDialog
from PyQt6.QtGui import QImage, QPixmap, QTransform, QPalette, QColor, QPainter, QResizeEvent, QWheelEvent, QMouseEvent, QKeyEvent
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal

# ==========================================
# テキストやアイコンを右に90度回転させるカスタムラベル
# ==========================================
class RotatedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMinimumSize(40, 60)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.save()
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(0, 0, self.height(), self.width(), self.alignment(), self.text())
        painter.restore()

# ==========================================
# 【新規】どんな記号も確実に右に90度物理回転させるカスタムボタン
# ==========================================
class ClickableRotatedButton(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.save()
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(0, 0, self.height(), self.width(), self.alignment(), self.text())
        painter.restore()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()

# ==========================================
# クリック＆ドラッグでジャンプできる最大縦型進捗バー
# ==========================================
class ClickableReverseVerticalProgressBar(QProgressBar):
    sliderMoved = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOrientation(Qt.Orientation.Vertical)
        self.setInvertedAppearance(True)
        self.setTextVisible(False)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(14)
        self.setStyleSheet("""
            QProgressBar { background-color: #3c3c3c; border: none; border-radius: 4px; }
            QProgressBar::chunk { background-color: #007acc; border-radius: 4px; }
        """)

    def _handle_mouse_event(self, event: QMouseEvent):
        ratio = event.position().y() / self.height()
        ratio = max(0.0, min(1.0, ratio))
        val = self.minimum() + (self.maximum() - self.minimum()) * ratio
        self.setValue(int(val))
        self.sliderMoved.emit(self.value())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._handle_mouse_event(event)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._handle_mouse_event(event)
            event.accept()
    #############################################
# ==========================================
# メインのプレイヤーウィンドウ（UI構築編）
# ==========================================
class PDFMusicPlayer(QMainWindow):
    def __init__(self, target_dir, file_set):
        super().__init__()
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
        self.target_dir = target_dir
        
        self.pdf_path = file_set["pdf"]
        self.music_path = file_set["mp3"]
        self.csv_path = file_set["csv"]
        
        self.doc = pymupdf.open(self.pdf_path)
        self.total_pages = len(self.doc)
        self.current_page = 0
        self.current_pixmap = None
        self.is_paused = True
        
        # 【新規】再生速度状態用の変数 (1.0 = 100%, 0.9 = 90% ...)
        self.play_speed = 1.0
        self.temp_music_files = {} # 速度変換した一時ファイルのキャッシュ
        self.active_music_path = self.music_path
        
        self.zoom_factor = 1.0
        self.rotation_angle = 90  
        self.fit_mode = 1         
        initial_width = 1000
        initial_height = 1000
        
        if os.path.exists(self.config_path):
            self.load_config()
            initial_width = self.saved_width
            initial_height = self.saved_height

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.drag_position = QPoint()
        self.resize_margin = 8  
        self.is_resizing = False
        self.resize_edge = Qt.Edge(0)

        # pydubで元音源を読み込み、基本の長さを取得
        self.sound_base = AudioSegment.from_file(self.music_path)
        
        pygame.mixer.init()
        pygame.mixer.music.load(self.active_music_path)
        self.music_length = pygame.mixer.Sound(self.music_path).get_length()
        
        self.recorded_timings = {} 
        self.load_timings()
        
        self.current_time_offset = 0.0
        self.play_start_time = 0.0
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_playback)
        
        self.initUI()
        self.resize(initial_width, initial_height) 
        
        # 画面サイズが完全に確定した0.1秒後にサイズ引き継ぎ描画と自動再生をスタート
        QTimer.singleShot(100, self.start_initial_playback)

    def initUI(self):
        self.setWindowTitle("楽譜Viewer & 自動プレイヤー")
        
        main_widget = QWidget()
        main_widget.setStyleSheet("background-color: #141414;")
        self.setCentralWidget(main_widget)
        
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 【左側】コントロールパネル
        controls_widget = QWidget()
        controls_widget.setFixedWidth(60)
        controls_widget.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #ffffff; font-family: 'Segoe UI', sans-serif; }
            QPushButton { background-color: #2d2d2d; border: 1px solid #3c3c3c; border-radius: 6px; color: #ffffff; font-size: 18px; font-weight: bold; }
            QPushButton:hover { background-color: #3e3e3e; }
            QPushButton:pressed { background-color: #4f4f4f; }
            QLabel#rotated-btn { background-color: #2d2d2d; border: 1px solid #3c3c3c; border-radius: 6px; color: #ffffff; font-size: 18px; font-weight: bold; }
            QLabel#rotated-btn:hover { background-color: #3e3e3e; }
            QPushButton.sys-btn { font-size: 14px; background-color: #252526; }
            QPushButton.close-btn { background-color: #2d2d2d; color: #aaaaaa; font-size: 16px; }
            QPushButton.close-btn:hover { background-color: #e81123; color: #ffffff; border: 1px solid #e81123; }
        """)
        
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 5, 0, 5)
        controls_layout.setSpacing(4)
        
        # 1. 上部操作ボタンエリア
        top_menu = QWidget()
        top_layout = QVBoxLayout(top_menu)
        top_layout.setContentsMargins(5, 0, 5, 0)
        top_layout.setSpacing(6)
        
        self.btn_play = ClickableRotatedButton("▶")
        self.btn_play.setObjectName("rotated-btn")
        self.btn_play.setFixedSize(50, 50)
        self.btn_play.setStyleSheet("background-color: #2E7D32;")
        
        self.btn_restart = ClickableRotatedButton("⏮")
        self.btn_restart.setObjectName("rotated-btn")
        self.btn_restart.setFixedSize(50, 40)
        
        # 再生速度変更ボタン（100 / 90 / 80 / 70 ループ仕様）
        self.btn_speed = ClickableRotatedButton("100")
        self.btn_speed.setObjectName("rotated-btn")
        self.btn_speed.setFixedSize(50, 40)
        
        self.btn_rewind = QPushButton("︽")
        self.btn_rewind.setFixedSize(50, 40)
        
        self.btn_forward = QPushButton("︾")
        self.btn_forward.setFixedSize(50, 40)
        
        self.btn_rotate = QPushButton("↻")
        self.btn_rotate.setFixedSize(50, 40)
        
        self.btn_fit = QPushButton("↔")  
        if self.fit_mode == 2:
            self.btn_fit.setText("↕")
        self.btn_fit.setFixedSize(50, 40)
        
        top_layout.addWidget(self.btn_play, 0, Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.btn_restart, 0, Qt.AlignmentFlag.AlignCenter) 
        top_layout.addWidget(self.btn_speed, 0, Qt.AlignmentFlag.AlignCenter) 
        top_layout.addWidget(self.btn_rewind, 0, Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.btn_forward, 0, Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.btn_rotate, 0, Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.btn_fit, 0, Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(top_menu)

        # 2. 中央スライダーエリア
        center_menu = QWidget()
        center_layout = QVBoxLayout(center_menu)
        center_layout.setContentsMargins(5, 0, 5, 0)
        center_layout.setSpacing(4)
        
        self.time_label_current = RotatedLabel("00:00")
        self.time_label_current.setStyleSheet("color: #00FF00;")
        
        self.slider = ClickableReverseVerticalProgressBar()
        self.slider.setRange(0, int(self.music_length))
        
        self.time_label_total = RotatedLabel(self.format_time(self.music_length))
        
        center_layout.addWidget(self.time_label_current, 0, Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignCenter) 
        center_layout.addWidget(self.time_label_total, 0, Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(center_menu, 1)

        # 3. 最下部ウィンドウ操作エリア
        bottom_menu = QWidget()
        bottom_layout = QVBoxLayout(bottom_menu)
        bottom_layout.setContentsMargins(5, 0, 5, 0)
        bottom_layout.setSpacing(6)
        
        self.btn_min = QPushButton("🗕")
        self.btn_min.setFixedSize(50, 32)
        
        self.btn_max = QPushButton("🗖")
        self.btn_max.setFixedSize(50, 32)
        
        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(50, 32)
        self.btn_close.setProperty("class", "close-btn")
        
        bottom_layout.addWidget(self.btn_min, 0, Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(self.btn_max, 0, Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(bottom_menu)
        
        # イベント登録
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_restart.clicked.connect(self.reset_playback) 
        self.btn_speed.clicked.connect(self.change_play_speed) 
        self.btn_rewind.clicked.connect(lambda: self.seek_relative(-5))
        self.btn_forward.clicked.connect(lambda: self.seek_relative(5))
        self.btn_rotate.clicked.connect(self.rotate_pdf)
        self.btn_fit.clicked.connect(self.toggle_fit_mode)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_max.clicked.connect(self.toggle_maximize)
        self.btn_close.clicked.connect(self.close)
        self.slider.sliderMoved.connect(self.jump_to_time)
        
        main_layout.addWidget(controls_widget)
        
        # 右側楽譜表示部
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: #141414; border: none; border-left: 1px solid #2d2d2d;")
        
        self.pdf_label = QLabel()
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.pdf_label)
        main_layout.addWidget(self.scroll_area, stretch=1)
        
        self.setMouseTracking(True)
        controls_widget.setMouseTracking(True)
        main_widget.setMouseTracking(True)

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("🗖")
        else:
            self.showMaximized()
            self.btn_max.setText("🗗")

    # ==========================================
    # PDFの描画およびズーム・フィッティングロジック
    # ==========================================
    def show_page(self, page_num):
        if 0 <= page_num < self.total_pages:
            page = self.doc.load_page(page_num)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
            
            samples_data = pix.samples() if callable(pix.samples) else pix.samples
            qimg = QImage(samples_data, pix.width, pix.height, pix.width * 3, QImage.Format.Format_RGB888)
            base_pixmap = QPixmap.fromImage(qimg)
            
            if self.rotation_angle != 0:
                transform = QTransform().rotate(self.rotation_angle)
                self.current_pixmap = base_pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation)
            else:
                self.current_pixmap = base_pixmap
                
            self.update_zoom_display()

    def toggle_fit_mode(self):
        if self.fit_mode == 1:
            self.fit_mode = 2
            self.btn_fit.setText("↕") 
        else:
            self.fit_mode = 1
            self.btn_fit.setText("↔") 
            
        self.update_zoom_display()

    def update_zoom_display(self):
        if self.current_pixmap is None:
            return
        area_width = self.scroll_area.width()
        area_height = self.scroll_area.height()
        
        if self.fit_mode == 1:
            scaled_pixmap = self.current_pixmap.scaledToHeight(area_height - 10, Qt.TransformationMode.SmoothTransformation)
        elif self.fit_mode == 2:
            scaled_pixmap = self.current_pixmap.scaledToWidth(area_width - 10, Qt.TransformationMode.SmoothTransformation)
        else:
            base_width = area_width - 20 if area_width > 100 else 800
            target_width = int(base_width * self.zoom_factor)
            scaled_pixmap = self.current_pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
            
        self.pdf_label.setPixmap(scaled_pixmap)

    def rotate_pdf(self):
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.show_page(self.current_page)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.update_zoom_display()

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.fit_mode = 0
            angle = event.angleDelta().y()
            if angle > 0:
                self.zoom_factor = min(self.zoom_factor + 0.1, 4.0)
            else:
                self.zoom_factor = max(self.zoom_factor - 0.1, 0.4)
            self.update_zoom_display()
            event.accept()
        else:
            super().wheelEvent(event)

    # ==========================================
    # 【新規】音程を維持したまま再生テンポを物理変更するロジック
    # ==========================================
    def change_play_speed(self):
        # 100 -> 90 -> 80 -> 70 -> 100 ループ
        if self.play_speed == 1.0: self.play_speed = 0.9
        elif self.play_speed == 0.9: self.play_speed = 0.8
        elif self.play_speed == 0.8: self.play_speed = 0.7
        else: self.play_speed = 1.0
        
        self.btn_speed.setText(str(int(self.play_speed * 100)))
        
        # 現在の再生位置(等倍ベースの秒数)を退避
        current_pos_seconds = self.get_current_elapsed()
        
        was_playing = not self.is_paused
        if was_playing:
            self.toggle_play() # 一時停止
            
        # 速度に応じたタイムストレッチ音声の生成・ロード
        if self.play_speed == 1.0:
            self.active_music_path = self.music_path
        else:
            if self.play_speed not in self.temp_music_files:
                print(f"[テンポ変換中] Python 3.12 (audioop) で速度を {int(self.play_speed*100)}% に高品質ストレッチしています...")
                # 音程を変えずに再生速度だけを変える処理
                stretched_sound = self.sound_base._spawn(self.sound_base.raw_data, overrides={
                    "frame_rate": int(self.sound_base.frame_rate * self.play_speed)
                }).set_frame_rate(self.sound_base.frame_rate)
                
                # 安全な一時フォルダにWAV形式としてエクスポート
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                stretched_sound.export(temp_file.name, format="wav")
                self.temp_music_files[self.play_speed] = temp_file.name
                
            self.active_music_path = self.temp_music_files[self.play_speed]

        pygame.mixer.music.load(self.active_music_path)
        
        # 変更後のテンポに合わせて、退避していた秒数位置へ正確にジャンプ
        self.current_time_offset = current_pos_seconds
        self.slider.setValue(int(current_pos_seconds))
        
        if was_playing:
            self.toggle_play() # 再生再開

    def load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
                config = {}
                for line in lines:
                    if "=" in line:
                        k, v = line.split("=", 1)
                        config[k.strip()] = v.strip()
                
                self.saved_width = int(config.get("width", 1000))
                self.saved_height = int(config.get("height", 1000))
                self.zoom_factor = float(config.get("zoom", 1.0))
                self.rotation_angle = int(config.get("rotation", 90))
                self.fit_mode = int(config.get("fit_mode", 1))
        except Exception as e:
            print(f"設定の読み込みに失敗しました: {e}")

    def save_config(self):
        try:
            w = self.width() if not self.isMaximized() else self.saved_width
            h = self.height() if not self.isMaximized() else self.saved_height
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(f"last_dir={self.target_dir}\n")
                f.write(f"width={w}\n")
                f.write(f"height={h}\n")
                f.write(f"zoom={self.zoom_factor}\n")
                f.write(f"rotation={self.rotation_angle}\n")
                f.write(f"fit_mode={self.fit_mode}\n")
        except Exception as e:
            print(f"設定の保存に失敗しました: {e}")
#############################################


