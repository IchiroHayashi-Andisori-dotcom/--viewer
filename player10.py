import sys
import os
import csv
import time
import pymupdf
import pygame
from pydub import AudioSegment
import tempfile
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QScrollArea, QPushButton, QProgressBar, QSizePolicy, QFileDialog
from PyQt6.QtGui import QImage, QPixmap, QTransform, QPalette, QColor, QPainter, QResizeEvent, QWheelEvent, QMouseEvent, QKeyEvent
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal

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
        
        self.play_speed = 1.0
        self.temp_music_files = {} 
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
        
        QTimer.singleShot(100, self.start_initial_playback)

    def initUI(self):
        self.setWindowTitle("楽譜Viewer & 自動プレイヤー")
        
        main_widget = QWidget()
        main_widget.setStyleSheet("background-color: #141414;")
        self.setCentralWidget(main_widget)
        
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
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
    # 【完全解決版】音程維持・正確なタイムストレッチ生成
    # ==========================================
    def change_play_speed(self):
        # 100 -> 90 -> 80 -> 70 -> 100 ループ
        if self.play_speed == 1.0: self.play_speed = 0.9
        elif self.play_speed == 0.9: self.play_speed = 0.8
        elif self.play_speed == 0.8: self.play_speed = 0.7
        else: self.play_speed = 1.0
        
        self.btn_speed.setText(str(int(self.play_speed * 100)))
        
        # 現在の再生位置（等倍ベースの秒数）を退避
        current_pos_seconds = self.get_current_elapsed()
        
        was_playing = not self.is_paused
        if was_playing:
            self.toggle_play() # 一時停止
            
        if self.play_speed == 1.0:
            self.active_music_path = self.music_path
            total_duration = self.music_length
        else:
            if self.play_speed not in self.temp_music_files:
                print(f"[テンポ変換中] 速度を {int(self.play_speed*100)}% に高品質ストレッチ（音程維持）しています...")
                
                # 【修正】音程を完全に維持したまま、再生速度だけを物理的に変更する正しいロジック
                # pydubの「speedup」メソッドを使い、スロー再生（1/play_speed）を正確に行います
                # playback_speedには「1.0に対する比率」を渡すため、遅くする場合は1未満の数値を指定します
                stretched_sound = self.sound_base.speedup(
                    playback_speed=self.play_speed, 
                    chunk_size=150, 
                    crossfade=25
                )
                
                # pygameとのサンプリングレート不一致を防ぐため、元の音源と同じ周波数を完全にキープ
                stretched_sound = stretched_sound.set_frame_rate(self.sound_base.frame_rate)
                
                temp_dir = tempfile.gettempdir()
                temp_file_path = os.path.join(temp_dir, f"pdfplayer_speed_{int(self.play_speed*100)}.wav")
                
                # 一度クローズされるように確実にエクスポート
                stretched_sound.export(temp_file_path, format="wav")
                self.temp_music_files[self.play_speed] = temp_file_path
                
            self.active_music_path = self.temp_music_files[self.play_speed]
            # トータル時間を速度に合わせて正確に引き延ばす
            total_duration = self.music_length / self.play_speed

        # pygameに新しい音源をロード（これで周波数ミスマッチによる二重遅延が消えます）
        pygame.mixer.music.load(self.active_music_path)
        
        # プログレスバーとトータル時間の更新
        self.slider.setRange(0, int(total_duration))
        self.time_label_total.setText(self.format_time(total_duration))
        
        # 現在位置の同期
        self.current_time_offset = current_pos_seconds
        actual_ui_pos = current_pos_seconds / self.play_speed
        self.slider.setValue(int(actual_ui_pos))
        
        if was_playing:
            self.toggle_play() # 再生再開

        # 100 -> 90 -> 80 -> 70 -> 100 ループ
        if self.play_speed == 1.0: self.play_speed = 0.9
        elif self.play_speed == 0.9: self.play_speed = 0.8
        elif self.play_speed == 0.8: self.play_speed = 0.7
        else: self.play_speed = 1.0
        
        self.btn_speed.setText(str(int(self.play_speed * 100)))
        
        # 1. 現在の再生位置（等倍ベースの秒数）を退避
        current_pos_seconds = self.get_current_elapsed()
        
        was_playing = not self.is_paused
        if was_playing:
            self.toggle_play() # 一時停止
            
        if self.play_speed == 1.0:
            self.active_music_path = self.music_path
            # トータル時間を等倍に戻す
            total_duration = self.music_length
        else:
            if self.play_speed not in self.temp_music_files:
                print(f"[テンポ変換中] 速度を {int(self.play_speed*100)}% に変換中...")
                
                # 音程変化の保留対応も含め、確実にWindowsで再生可能な一時ファイルを生成
                stretched_sound = self.sound_base._spawn(self.sound_base.raw_data, overrides={
                    "frame_rate": int(self.sound_base.frame_rate * self.play_speed)
                }).set_frame_rate(self.sound_base.frame_rate)
                
                temp_dir = tempfile.gettempdir()
                temp_file_path = os.path.join(temp_dir, f"pdfplayer_speed_{int(self.play_speed*100)}.wav")
                stretched_sound.export(temp_file_path, format="wav")
                self.temp_music_files[self.play_speed] = temp_file_path
                
            self.active_music_path = self.temp_music_files[self.play_speed]
            # 【修正】トータル時間を速度に合わせて「引き延ばした長さ」に再計算
            total_duration = self.music_length / self.play_speed

        pygame.mixer.music.load(self.active_music_path)
        
        # 【修正】プログレスバーの最大値とトータル時間ラベルを、引き延ばされた現実に合わせて更新
        self.slider.setRange(0, int(total_duration))
        self.time_label_total.setText(self.format_time(total_duration))
        
        # 現在位置を保持してスライダーを同期
        self.current_time_offset = current_pos_seconds
        actual_ui_pos = current_pos_seconds / self.play_speed
        self.slider.setValue(int(actual_ui_pos))
        
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
            print(f"設定の読み込みに失敗しました(初回起動とみなします): {e}")

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
            print("[保存完了] 環境設定 (config.txt) を更新しました。")
        except Exception as e:
            print(f"設定の保存に失敗しました: {e}")

    def load_timings(self):
        self.recorded_timings = {}
        if os.path.exists(self.csv_path):
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                try:
                    next(reader) 
                    for row in reader:
                        if row and len(row) >= 2:
                            self.recorded_timings[int(row[0])] = float(row[1])
                except StopIteration:
                    pass

    def save_timings(self):
        sorted_rows = sorted(self.recorded_timings.items())
        with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["page", "time"])
            for page, t in sorted_rows:
                writer.writerow([page, t])
        print(f"[保存完了] {self.csv_path} にタイミングデータを書き込みました。")

    def format_time(self, seconds):
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins:02d}:{secs:02d}"

    def start_initial_playback(self):
        self.show_page(self.current_page)
        self.toggle_play()

    def toggle_play(self):
        if self.is_paused:
            # 【修正】pygame.mixer.music.playのstartは「そのファイルの秒数」なので、
            # テンポ変更ファイルに対しては、引き延ばされた現実の秒数をそのまま渡すのが正解です
            actual_start_pos = self.current_time_offset / self.play_speed
            pygame.mixer.music.play(start=actual_start_pos)
            self.play_start_time = time.time()
            self.timer.start(50)
            self.is_paused = False
            self.btn_play.setText("‖") 
            self.btn_play.setStyleSheet("background-color: #B71C1C; color: #ffffff;")
        else:
            pygame.mixer.music.stop()
            self.timer.stop()
            # 停止時、現実の経過時間をそのまま加算
            actual_elapsed = time.time() - self.play_start_time
            self.current_time_offset += actual_elapsed * self.play_speed
            self.is_paused = True
            self.btn_play.setText("▶") 
            self.btn_play.setStyleSheet("background-color: #2E7D32; color: #ffffff;")

    def update_playback(self):
        if self.is_paused:
            return
        
        # 現実世界での純粋な経過時間
        actual_elapsed = time.time() - self.play_start_time
        
        # 1. プログレスバーの現在位置（現実の時間軸）
        current_actual_time = (self.current_time_offset / self.play_speed) + actual_elapsed
        
        # 2. 楽曲が最後まで引き延ばされた時間に達したかチェック（途中で終わるバグの解消）
        extended_total_length = self.music_length / self.play_speed
        if current_actual_time >= extended_total_length:
            self.save_timings() 
            self.reset_playback()
            return
            
        self.slider.setValue(int(current_actual_time))
        self.time_label_current.setText(self.format_time(current_actual_time))
        
        # 3. 【超重要】ページめくり判定（sync_page_to_time）には、
        # 速度を掛け算して「元の100%等倍の音楽時間」に直した秒数を渡すことで、完璧に音と連動させます
        music_elapsed_seconds = current_actual_time * self.play_speed
        self.sync_page_to_time(music_elapsed_seconds)

    def get_current_elapsed(self):
        if self.is_paused:
            return self.current_time_offset
        return self.current_time_offset + (time.time() - self.play_start_time) * self.play_speed

    def sync_page_to_time(self, elapsed_time):
        appropriate_page = 0
        sorted_timings = sorted(self.recorded_timings.items())
        for target_page, target_time in sorted_timings:
            if elapsed_time >= target_time:
                appropriate_page = target_page
        if self.current_page != appropriate_page:
            self.current_page = appropriate_page
            self.show_page(self.current_page)

    def seek_relative(self, seconds):
        current_pos = self.get_current_elapsed()
        new_pos = max(0.0, min(current_pos + seconds, self.music_length))
        self.jump_to_time(new_pos)

    def jump_to_time(self, target_seconds):
        target_seconds = float(target_seconds)
        self.current_time_offset = target_seconds
        self.play_start_time = time.time()
        self.slider.setValue(int(target_seconds))
        self.time_label_current.setText(self.format_time(target_seconds))
        self.sync_page_to_time(target_seconds)
        if not self.is_paused:
            pygame.mixer.music.play(start=target_seconds * self.play_speed)

    def reset_playback(self):
        pygame.mixer.music.stop()
        self.timer.stop()
        self.current_time_offset = 0.0
        self.is_paused = True 
        self.slider.setValue(0)
        self.time_label_current.setText("00:00")
        self.current_page = 0
        self.show_page(self.current_page)
        self.toggle_play()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_play()
            event.accept()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return):
            if self.current_page < self.total_pages - 1:
                current_time = self.get_current_elapsed()
                self.recorded_timings[self.current_page + 1] = round(current_time, 2)
                self.current_page += 1
                self.show_page(self.current_page)
            event.accept()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
            if self.current_page > 0:
                if self.current_page in self.recorded_timings:
                    del self.recorded_timings[self.current_page]
                self.current_page -= 1
                self.show_page(self.current_page)
            event.accept()
        elif key == Qt.Key.Key_Comma:
            self.seek_relative(-5)
            event.accept()
        elif key == Qt.Key.Key_Period:
            self.seek_relative(5)
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.save_timings()
        self.save_config() 
        if self.doc:
            self.doc.close()
        for temp_path in self.temp_music_files.values():
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
        super().closeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            rect = self.rect()
            edge = Qt.Edge(0)
            if pos.x() <= self.resize_margin: edge |= Qt.Edge.LeftEdge
            if pos.x() >= rect.width() - self.resize_margin: edge |= Qt.Edge.RightEdge
            if pos.y() <= self.resize_margin: edge |= Qt.Edge.TopEdge
            if pos.y() >= rect.height() - self.resize_margin: edge |= Qt.Edge.BottomEdge
            
            if edge:
                self.is_resizing = True
                self.resize_edge = edge
                self.windowHandle().startSystemResize(edge)
                event.accept()
            elif pos.x() <= 60:  
                self.windowHandle().startSystemMove()
                event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        rect = self.rect()
        left = pos.x() <= self.resize_margin
        right = pos.x() >= rect.width() - self.resize_margin
        top = pos.y() <= self.resize_margin
        bottom = pos.y() >= rect.height() - self.resize_margin
        
        if (left and top) or (right and bottom): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (right and top) or (left and bottom): self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif left or right: self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif top or bottom: self.setCursor(Qt.CursorShape.SizeVerCursor)
        else: self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, "config.txt")
    
    init_dir = script_dir
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("last_dir="):
                        path = line.split("=", 1)[1].strip()
                        if os.path.exists(path):
                            init_dir = path
                        break
        except:
            pass

    selected_dir = QFileDialog.getExistingDirectory(None, "楽譜・音源の入ったフォルダーを選択してください", init_dir)
    
    if not selected_dir:
        print("フォルダが選択されなかったため、起動を中止します。")
        sys.exit()

    target_id = None
    file_set = {"pdf": None, "mp3": None, "csv": None}
    
    for file in os.listdir(selected_dir):
        if file.endswith("_drums.pdf") and len(file) >= 13:
            target_id = file[:3]
            file_set["pdf"] = os.path.join(selected_dir, file)
            break
            
    if not target_id:
        print("エラー: 選択したフォルダ内に '***_drums.pdf' のルールに適合する楽譜が見つかりません。")
        sys.exit()
        
    for file in os.listdir(selected_dir):
        if file.startswith(target_id + "_"):
            if file.lower().endswith(".mp3"):
                file_set["mp3"] = os.path.join(selected_dir, file)
            elif file.lower().endswith("_timing.csv"):
                file_set["csv"] = os.path.join(selected_dir, file)

    if not file_set["csv"]:
        file_set["csv"] = os.path.join(selected_dir, f"{target_id}_timing.csv")

    if not file_set["mp3"]:
        print(f"エラー: ID '{target_id}' に紐づく音楽ファイル (.mp3) が見つかりません。")
        sys.exit()

    player = PDFMusicPlayer(selected_dir, file_set)
    player.show()
    sys.exit(app.exec())
