import sys
import psutil
import time
import threading
import winreg
import socket
import ctypes
from ctypes import wintypes
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QComboBox, QCheckBox, QSpinBox, QPushButton, 
                            QColorDialog, QSystemTrayIcon, QMenu, QMessageBox, QGroupBox,
                            QTabWidget, QScrollArea, QGridLayout, QDoubleSpinBox, QStackedWidget,
                            QTableWidget, QGraphicsView, QGraphicsScene, QGraphicsItem, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QSize, QSettings, QPointF, QRectF, QByteArray
from PyQt5.QtGui import (QColor, QIcon, QFont, QPainter, QLinearGradient, QPen, 
                         QBrush, QPolygonF, QPainterPath)
from win32api import GetMonitorInfo, MonitorFromPoint
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

__version__ = '4.0'  # 版本号

class SpeedMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        # 设置实时自动保存：500ms 防抖单次定时器
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.timeout.connect(self._save_settings_now)
        self.init_settings()
        self.init_ui()
        self.init_tray()
        self.init_network()
        self.init_history()
        self.init_web_server()
        # 连接所有设置控件变更信号 → 自动保存
        self._connect_autosave()
        
        # 恢复窗口大小和位置
        geometry = self.settings.value('window_geometry')
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode('utf-8')))
        
        # 启动网速监测线程
        self.monitor_thread = threading.Thread(target=self.monitor_speed, daemon=True)
        self.monitor_thread.start()
        
        # 更新UI的定时器
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(1000)
        
        # 历史记录定时器
        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self.update_history)
        self.history_timer.start(5000)  # 每5秒记录一次

        # 初始化任务栏显示
        if self.settings.value('show_taskbar', True, type=bool):
            self.init_taskbar()
            
        # 根据设置决定初始状态
        if self.settings.value('start_minimized', False, type=bool):
            if self.settings.value('minimize_location', 'tray') == 'tray':
                self.hide()
            else:
                self.showMinimized()
        # 初始化任务栏标题显示
        if self.settings.value('show_taskbar', True, type=bool):
            self.setWindowTitle(f'网速监测工具 - 增强版 v{__version__}')
            
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle(f'网速监测工具 - 增强版 v{__version__}')
        self.setWindowIcon(QIcon('icon.ico'))
        self.setMinimumSize(800, 600)
        
        # 主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # 使用选项卡布局
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)
        
        # 网速显示标签
        self.speed_label = QLabel("0 KB/s")
        self.speed_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.speed_label)
        
        # 基本设置选项卡
        basic_tab = QWidget()
        tab_widget.addTab(basic_tab, "基本设置")
        self.setup_basic_tab(basic_tab)
        
        # 显示设置选项卡
        display_tab = QWidget()
        tab_widget.addTab(display_tab, "显示设置")
        self.setup_display_tab(display_tab)
        
        # 颜色设置选项卡
        color_tab = QWidget()
        tab_widget.addTab(color_tab, "颜色设置")
        self.setup_color_tab(color_tab)
        
        # 行为设置选项卡
        behavior_tab = QWidget()
        tab_widget.addTab(behavior_tab, "行为设置")
        self.setup_behavior_tab(behavior_tab)
        
        # 历史记录选项卡
        history_tab = QWidget()
        tab_widget.addTab(history_tab, "历史记录")
        self.setup_history_tab(history_tab)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        
        self.default_btn = QPushButton('恢复默认值')
        self.default_btn.clicked.connect(self.restore_defaults)
        btn_layout.addWidget(self.default_btn)
        
        self.apply_btn = QPushButton('应用设置')
        self.apply_btn.clicked.connect(self.apply_settings)
        btn_layout.addWidget(self.apply_btn)
        
        main_layout.addLayout(btn_layout)
        
        # 初始化浮动窗口
        self.floating_windows = {}  # 存储每个显示器的浮动窗口
        self.init_floating_windows()
        
        # 根据设置决定初始状态
        if self.settings.value('start_minimized', False, type=bool):
            if self.settings.value('minimize_location', 'tray') == 'tray':
                self.hide()
            else:
                self.showMinimized()

        # 初始化任务栏显示
        if self.settings.value('show_taskbar', True, type=bool):
            self.setWindowTitle(f'网速监测工具 - 增强版 v{__version__}')
    
    def init_floating_windows(self):
        """初始化浮动窗口，为每个显示器创建一个"""
        # 先关闭现有的浮动窗口
        for window in self.floating_windows.values():
            window.close()
        self.floating_windows = {}
        
        # 获取所有显示器信息
        monitors = self.get_all_monitors()
        
        for i, monitor in enumerate(monitors):
            floating_window = FloatingWindow(monitor['index'])
            floating_window.setWindowOpacity(self.settings.value(f'float_opacity_{i}', 0.9, type=float))
            
            # 设置浮动窗口位置
            position = self.settings.value(f'display_position_{i}', '右下角')
            if position == '自定义位置':
                x = self.settings.value(f'custom_x_{i}', 0, type=int)
                y = self.settings.value(f'custom_y_{i}', 0, type=int)
                floating_window.move(x, y)
            else:
                self.update_floating_position(floating_window, monitor, position)
            
            # 根据设置决定是否显示
            if self.settings.value('show_floating', False, type=bool):
                floating_window.show()
            
            self.floating_windows[monitor['index']] = floating_window
    
    def init_taskbar(self):
        """初始化任务栏显示"""
        self.taskbar_hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        self.taskbar_label = QLabel()
        self.taskbar_label.setAlignment(Qt.AlignCenter)
        self.taskbar_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                padding: 0 5px;
            }
        """)
        
        # 创建一个透明窗口来承载标签
        self.taskbar_window = QWidget()
        self.taskbar_window.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint |  # 添加这个标志确保窗口在最上层
            Qt.Tool | 
            Qt.X11BypassWindowManagerHint
        )
        self.taskbar_window.setAttribute(Qt.WA_TranslucentBackground)
        self.taskbar_window.setAttribute(Qt.WA_ShowWithoutActivating)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.taskbar_label)
        self.taskbar_window.setLayout(layout)
        
        # 设置窗口位置
        self.update_taskbar_position()
        
        # 根据设置决定是否显示
        if self.settings.value('show_taskbar', True, type=bool):
            self.taskbar_window.show()

    def update_taskbar_position(self):
        """更新任务栏窗口位置"""
        if not hasattr(self, 'taskbar_hwnd'):
            return
            
        # 获取任务栏矩形
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.taskbar_hwnd, ctypes.byref(rect))
        
        # 计算位置（右侧）
        width = 150  # 固定宽度
        height = rect.bottom - rect.top
        x = rect.right - width - 10  # 右侧留出10px边距
        y = rect.top
        
        # 设置窗口位置和大小
        self.taskbar_window.setGeometry(x, y, width, height)
        self.taskbar_window.resize(width, height)
        self.taskbar_window.move(x, y)  # 确保窗口位置更新

    def get_all_monitors(self):
        """获取所有显示器信息"""
        import win32api
        import win32con
        
        monitors = []
        monitor_handles = win32api.EnumDisplayMonitors()
        
        for i, (handle, _, _) in enumerate(monitor_handles):
            monitor_info = win32api.GetMonitorInfo(handle)
            monitors.append({
                'index': i,
                'handle': handle,
                'work_area': monitor_info.get("Work"),
                'monitor_area': monitor_info.get("Monitor"),
                'name': monitor_info.get("Device", f"显示器 {i+1}")
            })
        
        return monitors
    
    def setup_basic_tab(self, tab):
        """设置基本设置选项卡"""
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # 网卡设置组
        network_group = QGroupBox("网卡设置")
        network_layout = QVBoxLayout()
        
        # 网卡选择
        self.interface_combo = QComboBox()
        network_layout.addWidget(QLabel('选择监测网卡:'))
        network_layout.addWidget(self.interface_combo)
        
        # 显示模式
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItems(['总网速', '单个网卡'])
        network_layout.addWidget(QLabel('显示模式:'))
        network_layout.addWidget(self.display_mode_combo)
        
        # 显示内容
        self.display_content_combo = QComboBox()
        self.display_content_combo.addItems(['上传+下载', '仅上传', '仅下载'])
        network_layout.addWidget(QLabel('显示内容:'))
        network_layout.addWidget(self.display_content_combo)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        # 单位设置组
        unit_group = QGroupBox("单位设置")
        unit_layout = QVBoxLayout()
        
        # 单位选择
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(['自动选择', 'bps', 'Kbps', 'Mbps', 'B/s', 'KB/s', 'MB/s'])
        unit_layout.addWidget(QLabel('显示单位:'))
        unit_layout.addWidget(self.unit_combo)
        
        # 是否显示单位
        self.show_unit_check = QCheckBox('显示单位')
        self.show_unit_check.setChecked(True)
        unit_layout.addWidget(self.show_unit_check)
        
        unit_group.setLayout(unit_layout)
        layout.addWidget(unit_group)
        
        layout.addStretch()
    
    def setup_display_tab(self, tab):
        """设置显示设置选项卡"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tab.layout = QVBoxLayout(tab)
        tab.layout.addWidget(scroll)
        
        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        
        # 主窗口显示设置
        main_display_group = QGroupBox("主窗口显示设置")
        main_layout = QGridLayout()
        
        # 字体大小
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 72)
        main_layout.addWidget(QLabel('字体大小:'), 0, 0)
        main_layout.addWidget(self.font_size, 0, 1)
        
        # 任务栏显示
        self.taskbar_check = QCheckBox('在任务栏显示网速')
        self.taskbar_check.setChecked(self.settings.value('show_taskbar', True, type=bool))
        self.taskbar_check.stateChanged.connect(self.toggle_taskbar_display)
        main_layout.addWidget(self.taskbar_check, 1, 0, 1, 2)
        
        # 浮动窗口显示
        self.float_check = QCheckBox('显示浮动窗口')
        self.float_check.setChecked(self.settings.value('show_floating', False, type=bool))
        self.float_check.stateChanged.connect(self.toggle_floating_display)
        main_layout.addWidget(self.float_check, 2, 0, 1, 2)
        
        main_display_group.setLayout(main_layout)
        layout.addWidget(main_display_group)
        
        # 浮动窗口设置
        float_group = QGroupBox("浮动窗口设置")
        float_layout = QGridLayout()
        
        # 获取所有显示器
        monitors = self.get_all_monitors()
        
        for i, monitor in enumerate(monitors):
            monitor_group = QGroupBox(f"{monitor['name']} 设置")
            monitor_layout = QGridLayout()
            
            # 显示位置
            position_combo = QComboBox()
            position_combo.addItems(['左上角', '右上角', '左下角', '右下角', '自定义位置'])
            position_combo.setCurrentText(self.settings.value(f'display_position_{i}', '右下角'))
            position_combo.setObjectName(f'position_combo_{i}')
            monitor_layout.addWidget(QLabel('显示位置:'), 0, 0)
            monitor_layout.addWidget(position_combo, 0, 1)
            
            # 自定义位置
            x_pos = QSpinBox()
            x_pos.setRange(0, 5000)
            x_pos.setValue(self.settings.value(f'custom_x_{i}', 0, type=int))
            x_pos.setObjectName(f'x_pos_{i}')
            monitor_layout.addWidget(QLabel('X坐标:'), 1, 0)
            monitor_layout.addWidget(x_pos, 1, 1)
            
            y_pos = QSpinBox()
            y_pos.setRange(0, 5000)
            y_pos.setValue(self.settings.value(f'custom_y_{i}', 0, type=int))
            y_pos.setObjectName(f'y_pos_{i}')
            monitor_layout.addWidget(QLabel('Y坐标:'), 2, 0)
            monitor_layout.addWidget(y_pos, 2, 1)
            
            # 浮动窗口透明度
            opacity = QDoubleSpinBox()
            opacity.setRange(0.1, 1.0)
            opacity.setSingleStep(0.1)
            opacity.setValue(self.settings.value(f'float_opacity_{i}', 0.9, type=float))
            opacity.setObjectName(f'float_opacity_{i}')
            monitor_layout.addWidget(QLabel('窗口透明度:'), 3, 0)
            monitor_layout.addWidget(opacity, 3, 1)
            
            monitor_group.setLayout(monitor_layout)
            float_layout.addWidget(monitor_group, i+1, 0, 1, 2)
        
        float_group.setLayout(float_layout)
        layout.addWidget(float_group)
        
        # 浮动窗口显示选项
        float_options_group = QGroupBox("浮动窗口显示选项")
        float_options_layout = QGridLayout()
        
        self.float_show_mini_graph = QCheckBox('显示迷你图表')
        self.float_show_mini_graph.setChecked(self.settings.value('float_show_mini_graph', True, type=bool))
        float_options_layout.addWidget(self.float_show_mini_graph, 0, 0)
        
        self.float_show_upload = QCheckBox('显示上传速度')
        self.float_show_upload.setChecked(self.settings.value('float_show_upload', True, type=bool))
        float_options_layout.addWidget(self.float_show_upload, 0, 1)
        
        self.float_show_download = QCheckBox('显示下载速度')
        self.float_show_download.setChecked(self.settings.value('float_show_download', True, type=bool))
        float_options_layout.addWidget(self.float_show_download, 1, 0)
        
        self.float_show_total = QCheckBox('显示总速度')
        self.float_show_total.setChecked(self.settings.value('float_show_total', True, type=bool))
        float_options_layout.addWidget(self.float_show_total, 1, 1)
        
        self.float_show_unit = QCheckBox('显示单位')
        self.float_show_unit.setChecked(self.settings.value('float_show_unit', True, type=bool))
        float_options_layout.addWidget(self.float_show_unit, 2, 0)
        
        float_options_group.setLayout(float_options_layout)
        layout.addWidget(float_options_group)
        
        layout.addStretch()
    
    def setup_color_tab(self, tab):
        """设置颜色设置选项卡"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tab.layout = QVBoxLayout(tab)
        tab.layout.addWidget(scroll)
        
        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        
        # 颜色模式选择
        self.color_mode_combo = QComboBox()
        self.color_mode_combo.addItems(['三色模式', '渐变模式', '自定义分段模式', '速度映射模式'])
        self.color_mode_combo.currentTextChanged.connect(self.update_color_ui)
        layout.addWidget(QLabel('颜色模式:'))
        layout.addWidget(self.color_mode_combo)
        
        # 单位选择
        layout.addWidget(QLabel('阈值单位:'))
        self.color_unit_combo = QComboBox()
        self.color_unit_combo.addItems(['KB/s', 'MB/s', 'Mbps', '自动调整'])
        layout.addWidget(self.color_unit_combo)
        self.color_unit_combo.currentTextChanged.connect(self.update_threshold_units)
        
        # 修改现有阈值控件的范围
        #self.slow_threshold.setRange(0, 1000000)  # 上限1000Gbps
        #self.fast_threshold.setRange(0, 1000000)
        #self.max_speed_spin.setRange(1, 1000000)
        #self.map_speed_spin.setRange(1, 1000000)

        # 颜色设置堆叠窗口
        self.color_stacks = QStackedWidget()
        layout.addWidget(self.color_stacks)
        
        # 三色模式
        tri_color_widget = QWidget()
        tri_layout = QVBoxLayout()
        
        self.slow_color_btn = QPushButton('低速颜色')
        self.slow_color_btn.clicked.connect(lambda: self.choose_color('slow'))
        tri_layout.addWidget(self.slow_color_btn)
        
        self.medium_color_btn = QPushButton('中速颜色')
        self.medium_color_btn.clicked.connect(lambda: self.choose_color('medium'))
        tri_layout.addWidget(self.medium_color_btn)
        
        self.fast_color_btn = QPushButton('高速颜色')
        self.fast_color_btn.clicked.connect(lambda: self.choose_color('fast'))
        tri_layout.addWidget(self.fast_color_btn)
        
        # 阈值设置
        tri_threshold_layout = QHBoxLayout()
        
        self.slow_threshold = QSpinBox()
        self.slow_threshold.setRange(0, 1000000)
        self.slow_threshold.setValue(self.settings.value('slow_threshold', 100, type=int))
        tri_threshold_layout.addWidget(QLabel('低速阈值(KB/s):'))
        tri_threshold_layout.addWidget(self.slow_threshold)
        
        self.fast_threshold = QSpinBox()
        self.fast_threshold.setRange(0, 1000000)
        self.fast_threshold.setValue(self.settings.value('fast_threshold', 1000, type=int))
        tri_threshold_layout.addWidget(QLabel('高速阈值(KB/s):'))
        tri_threshold_layout.addWidget(self.fast_threshold)
        
        tri_layout.addLayout(tri_threshold_layout)
        tri_color_widget.setLayout(tri_layout)
        self.color_stacks.addWidget(tri_color_widget)
        
        # 渐变模式
        gradient_widget = QWidget()
        grad_layout = QVBoxLayout()
        
        self.start_color_btn = QPushButton('起始颜色')
        self.start_color_btn.clicked.connect(lambda: self.choose_color('gradient_start'))
        grad_layout.addWidget(self.start_color_btn)
        
        self.end_color_btn = QPushButton('结束颜色')
        self.end_color_btn.clicked.connect(lambda: self.choose_color('gradient_end'))
        grad_layout.addWidget(self.end_color_btn)
        
        self.max_speed_spin = QSpinBox()
        self.max_speed_spin.setRange(1, 10000)
        self.max_speed_spin.setValue(self.settings.value('max_speed', 1000, type=int))
        grad_layout.addWidget(QLabel('最大速度(KB/s):'))
        grad_layout.addWidget(self.max_speed_spin)
        
        gradient_widget.setLayout(grad_layout)
        self.color_stacks.addWidget(gradient_widget)
        
        # 自定义分段模式
        segment_widget = QWidget()
        seg_layout = QVBoxLayout()
        
        self.segment_table = QTableWidget()
        self.segment_table.setColumnCount(3)
        self.segment_table.setHorizontalHeaderLabels(['阈值(KB/s)', '颜色', '操作'])
        self.segment_table.horizontalHeader().setStretchLastSection(True)
        
        add_segment_btn = QPushButton('添加分段')
        add_segment_btn.clicked.connect(self.add_color_segment)
        
        seg_layout.addWidget(self.segment_table)
        seg_layout.addWidget(add_segment_btn)
        segment_widget.setLayout(seg_layout)
        self.color_stacks.addWidget(segment_widget)
        
        # 速度映射模式
        map_widget = QWidget()
        map_layout = QVBoxLayout()
        
        self.map_speed_spin = QSpinBox()
        self.map_speed_spin.setRange(1, 1000)
        self.map_speed_spin.setValue(self.settings.value('map_speed', 100, type=int))
        map_layout.addWidget(QLabel('每多少KB/s变化一次颜色:'))
        map_layout.addWidget(self.map_speed_spin)
        
        self.map_start_color_btn = QPushButton('起始颜色')
        self.map_start_color_btn.clicked.connect(lambda: self.choose_color('map_start'))
        map_layout.addWidget(self.map_start_color_btn)
        
        self.map_end_color_btn = QPushButton('结束颜色')
        self.map_end_color_btn.clicked.connect(lambda: self.choose_color('map_end'))
        map_layout.addWidget(self.map_end_color_btn)
        
        map_widget.setLayout(map_layout)
        self.color_stacks.addWidget(map_widget)
        
        layout.addStretch()
    
    def setup_behavior_tab(self, tab):
        """设置行为设置选项卡"""
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # 启动设置组
        startup_group = QGroupBox("启动设置")
        startup_layout = QVBoxLayout()
        
        self.startup_check = QCheckBox('开机自动启动')
        self.startup_check.setChecked(self.settings.value('startup', False, type=bool))
        startup_layout.addWidget(self.startup_check)
        
        self.start_minimized_check = QCheckBox('启动时最小化')
        self.start_minimized_check.setChecked(self.settings.value('start_minimized', False, type=bool))
        startup_layout.addWidget(self.start_minimized_check)
        
        self.minimize_location_combo = QComboBox()
        self.minimize_location_combo.addItems(['任务栏', '系统托盘'])
        self.minimize_location_combo.setCurrentText(self.settings.value('minimize_location', '系统托盘'))
        startup_layout.addWidget(QLabel('最小化到:'))
        startup_layout.addWidget(self.minimize_location_combo)
        
        startup_group.setLayout(startup_layout)
        layout.addWidget(startup_group)
        
        # 关闭行为组
        close_group = QGroupBox("关闭行为设置")
        close_layout = QVBoxLayout()
        
        self.close_action_combo = QComboBox()
        self.close_action_combo.addItems(['最小化到任务栏', '最小化到托盘', '直接退出'])
        self.close_action_combo.setCurrentText(self.settings.value('close_action', '最小化到托盘'))
        close_layout.addWidget(QLabel('点击关闭按钮时:'))
        close_layout.addWidget(self.close_action_combo)
        
        close_group.setLayout(close_layout)
        layout.addWidget(close_group)
        
        # Web服务器设置
        web_group = QGroupBox("Web服务器设置")
        web_layout = QGridLayout()
        
        self.web_enable_check = QCheckBox('启用Web服务器')
        self.web_enable_check.setChecked(self.settings.value('web_enable', False, type=bool))
        web_layout.addWidget(self.web_enable_check, 0, 0, 1, 2)
        
        self.web_port_spin = QSpinBox()
        self.web_port_spin.setRange(1024, 65535)
        self.web_port_spin.setValue(self.settings.value('web_port', 8080, type=int))
        web_layout.addWidget(QLabel('端口:'), 1, 0)
        web_layout.addWidget(self.web_port_spin, 1, 1)
        
        web_group.setLayout(web_layout)
        layout.addWidget(web_group)
        
        layout.addStretch()
    
    def setup_history_tab(self, tab):
        """设置历史记录选项卡"""
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # 历史图表
        self.history_graph = QGraphicsView()
        self.history_graph.setRenderHint(QPainter.Antialiasing)
        self.history_graph.setScene(QGraphicsScene(self))
        self.history_graph.setMinimumHeight(300)
        
        layout.addWidget(self.history_graph)
        
        # 历史记录设置
        history_group = QGroupBox("历史记录设置")
        history_layout = QGridLayout()
        
        self.history_duration = QSpinBox()
        self.history_duration.setRange(1, 24)
        self.history_duration.setValue(self.settings.value('history_duration', 6, type=int))
        self.history_duration.setSuffix(" 小时")
        history_layout.addWidget(QLabel('记录时长:'), 0, 0)
        history_layout.addWidget(self.history_duration, 0, 1)
        
        self.history_interval = QSpinBox()
        self.history_interval.setRange(1, 60)
        self.history_interval.setValue(self.settings.value('history_interval', 5, type=int))
        self.history_interval.setSuffix(" 秒")
        history_layout.addWidget(QLabel('记录间隔:'), 1, 0)
        history_layout.addWidget(self.history_interval, 1, 1)
        
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)
        
        layout.addStretch()
    
    def init_settings(self):
        """初始化设置"""
        self.settings = QSettings("NetSpeedMonitor", "Enhanced")

        # 单位设置
        self.settings.setValue('color_unit', self.settings.value('color_unit', 'KB/s'))

        # 加载时转换单位
        slow_kb = self.settings.value('slow_threshold', 100, type=int)
        fast_kb = self.settings.value('fast_threshold', 1000, type=int)
        max_kb = self.settings.value('max_speed', 1000, type=int)
        map_kb = self.settings.value('map_speed', 100, type=int)
        
        # 设置单位选择
        if hasattr(self, 'color_unit_combo'):
            self.color_unit_combo.setCurrentText(self.settings.value('color_unit'))
        
        # 设置显示值（自动转换单位）
        if hasattr(self, 'slow_threshold'):
            self.slow_threshold.setValue(self.convert_color_threshold(slow_kb, False))
            self.fast_threshold.setValue(self.convert_color_threshold(fast_kb, False))
            self.max_speed_spin.setValue(self.convert_color_threshold(max_kb, False))
            self.map_speed_spin.setValue(self.convert_color_threshold(map_kb, False))
        

        # 加载保存的设置或使用默认值
        self.settings.beginGroup("Main")
        
        # 网络设置
        self.settings.setValue('interface', self.settings.value('interface', ''))
        self.settings.setValue('display_mode', self.settings.value('display_mode', '总网速'))
        self.settings.setValue('display_content', self.settings.value('display_content', '上传+下载'))
        self.settings.setValue('unit', self.settings.value('unit', '自动选择'))
        self.settings.setValue('show_unit', self.settings.value('show_unit', True, type=bool))
        
        # 显示设置
        self.settings.setValue('font_size', self.settings.value('font_size', 12, type=int))
        self.settings.setValue('show_taskbar', self.settings.value('show_taskbar', True, type=bool))
        self.settings.setValue('show_floating', self.settings.value('show_floating', False, type=bool))
        
        # 为每个显示器初始化设置
        monitors = self.get_all_monitors()
        for i, monitor in enumerate(monitors):
            self.settings.setValue(f'display_position_{i}', self.settings.value(f'display_position_{i}', '右下角'))
            self.settings.setValue(f'custom_x_{i}', self.settings.value(f'custom_x_{i}', 0, type=int))
            self.settings.setValue(f'custom_y_{i}', self.settings.value(f'custom_y_{i}', 0, type=int))
            self.settings.setValue(f'float_opacity_{i}', self.settings.value(f'float_opacity_{i}', 0.9, type=float))
        
        # 浮动窗口显示选项
        self.settings.setValue('float_show_mini_graph', self.settings.value('float_show_mini_graph', True, type=bool))
        self.settings.setValue('float_show_upload', self.settings.value('float_show_upload', True, type=bool))
        self.settings.setValue('float_show_download', self.settings.value('float_show_download', True, type=bool))
        self.settings.setValue('float_show_total', self.settings.value('float_show_total', True, type=bool))
        self.settings.setValue('float_show_unit', self.settings.value('float_show_unit', True, type=bool))
        
        # 颜色设置
        self.settings.setValue('color_mode', self.settings.value('color_mode', '三色模式'))
        
        # 三色模式
        self.settings.setValue('slow_color', self.settings.value('slow_color', QColor(0, 255, 0)))
        self.settings.setValue('medium_color', self.settings.value('medium_color', QColor(255, 255, 0)))
        self.settings.setValue('fast_color', self.settings.value('fast_color', QColor(255, 0, 0)))
        self.settings.setValue('slow_threshold', self.settings.value('slow_threshold', 100, type=int))
        self.settings.setValue('fast_threshold', self.settings.value('fast_threshold', 1000, type=int))
        
        # 渐变模式
        self.settings.setValue('gradient_start', self.settings.value('gradient_start', QColor(0, 255, 0)))
        self.settings.setValue('gradient_end', self.settings.value('gradient_end', QColor(255, 0, 0)))
        self.settings.setValue('max_speed', self.settings.value('max_speed', 1000, type=int))
        
        # 自定义分段模式
        self.settings.beginWriteArray("color_segments")
        for i in range(self.settings.value("color_segments/size", 0, type=int)):
            self.settings.setArrayIndex(i)
            # 这里可以加载保存的分段设置
        self.settings.endArray()
        
        # 速度映射模式
        self.settings.setValue('map_speed', self.settings.value('map_speed', 100, type=int))
        self.settings.setValue('map_start', self.settings.value('map_start', QColor(0, 255, 0)))
        self.settings.setValue('map_end', self.settings.value('map_end', QColor(255, 0, 0)))
        
        # 行为设置
        self.settings.setValue('startup', self.settings.value('startup', False, type=bool))
        self.settings.setValue('start_minimized', self.settings.value('start_minimized', False, type=bool))
        self.settings.setValue('minimize_location', self.settings.value('minimize_location', '系统托盘'))
        self.settings.setValue('close_action', self.settings.value('close_action', '最小化到托盘'))
        
        # Web服务器设置
        self.settings.setValue('web_enable', self.settings.value('web_enable', False, type=bool))
        self.settings.setValue('web_port', self.settings.value('web_port', 8080, type=int))
        
        # 历史记录设置
        self.settings.setValue('history_duration', self.settings.value('history_duration', 6, type=int))
        self.settings.setValue('history_interval', self.settings.value('history_interval', 5, type=int))
        
        self.settings.endGroup()
        
        # 设置开机自启
        self.set_auto_start(self.settings.value('startup', False, type=bool))
    

    def convert_color_threshold(self, value, to_kb=True):
        """单位转换工具"""
        unit = self.settings.value('color_unit', 'KB/s')
        
        if unit == 'MB/s':
            return value * 1024 if to_kb else value / 1024
        elif unit == 'Mbps':
            return value * 125 if to_kb else value / 125  # 1Mbps = 125KB/s
        return value

    def update_threshold_units(self):
        """当单位改变时自动换算阈值"""
        if not hasattr(self, 'slow_threshold'):
            return
        
        # 获取当前值（旧单位）
        old_slow = self.slow_threshold.value()
        old_fast = self.fast_threshold.value()
        old_max = self.max_speed_spin.value()
        old_map = self.map_speed_spin.value()
        
        # 先转换为KB/s
        slow_kb = self.convert_color_threshold(old_slow)
        fast_kb = self.convert_color_threshold(old_fast)
        max_kb = self.convert_color_threshold(old_max)
        map_kb = self.convert_color_threshold(old_map)
        
        # 再转换为新单位显示
        self.slow_threshold.setValue(self.convert_color_threshold(slow_kb, False))
        self.fast_threshold.setValue(self.convert_color_threshold(fast_kb, False))
        self.max_speed_spin.setValue(self.convert_color_threshold(max_kb, False))
        self.map_speed_spin.setValue(self.convert_color_threshold(map_kb, False))

    def init_history(self):
        """初始化历史记录"""
        self.history_data = {
            'time': [],
            'upload': [],
            'download': []
        }
        self.max_history_points = self.settings.value('history_duration', 6, type=int) * 3600 / self.settings.value('history_interval', 5, type=int)
    
    def init_web_server(self):
        """初始化Web服务器"""
        self.web_server = None
        if self.settings.value('web_enable', False, type=bool):
            self.start_web_server()
    
    def start_web_server(self):
        """启动Web服务器"""
        if self.web_server:
            self.web_server.shutdown()
        
        port = self.settings.value('web_port', 8080, type=int)
        
        class SpeedRequestHandler(BaseHTTPRequestHandler):
            def do_GET(handler):
                if handler.path == '/speed':
                    handler.send_response(200)
                    handler.send_header('Content-type', 'application/json')
                    handler.end_headers()
                    
                    # 获取当前网速
                    if not self.current_speeds:
                        handler.wfile.write(b'{"upload": 0, "download": 0}')
                        return
                    
                    if self.settings.value('display_mode') == '总网速':
                        total_up = sum(speed['upload'] for speed in self.current_speeds.values())
                        total_down = sum(speed['download'] for speed in self.current_speeds.values())
                    else:
                        if self.settings.value('interface') in self.current_speeds:
                            total_up = self.current_speeds[self.settings.value('interface')]['upload']
                            total_down = self.current_speeds[self.settings.value('interface')]['download']
                        else:
                            total_up = total_down = 0
                    
                    # 转换为KB/s
                    up_kb = total_up / 1024
                    down_kb = total_down / 1024
                    
                    response = f'{{"upload": {up_kb:.2f}, "download": {down_kb:.2f}}}'
                    handler.wfile.write(response.encode())
                else:
                    handler.send_response(404)
                    handler.end_headers()
        
        class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
            pass
        
        try:
            self.web_server = ThreadedHTTPServer(('0.0.0.0', port), SpeedRequestHandler)
            server_thread = threading.Thread(target=self.web_server.serve_forever, daemon=True)
            server_thread.start()
        except Exception as e:
            QMessageBox.warning(self, "Web服务器错误", f"无法启动Web服务器: {str(e)}")
    
    def set_auto_start(self, enable):
        """设置开机自动启动"""
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        try:
            with winreg.OpenKey(key, key_path, 0, winreg.KEY_ALL_ACCESS) as registry_key:
                if enable:
                    winreg.SetValueEx(registry_key, "NetSpeedMonitor", 0, winreg.REG_SZ, sys.executable + ' "' + sys.argv[0] + '"')
                else:
                    try:
                        winreg.DeleteValue(registry_key, "NetSpeedMonitor")
                    except WindowsError:
                        pass
        except WindowsError:
            QMessageBox.warning(self, "警告", "无法设置开机自启!")
    
    def init_tray(self):
        """初始化系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('icon.ico'))
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("显示主窗口")
        show_action.triggered.connect(self.show_normal)
        
        exit_action = tray_menu.addAction("退出")
        exit_action.triggered.connect(self.close_app)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        # 托盘图标点击事件
        self.tray_icon.activated.connect(self.tray_icon_clicked)
    
    def init_network(self):
        """初始化网络监测"""
        self.network_stats = {}
        self.current_speeds = {}
        self.last_stats = {}
        self.last_time = time.time()
        
        # 获取所有网络接口
        interfaces = psutil.net_io_counters(pernic=True).keys()
        self.interface_combo.clear()
        self.interface_combo.addItems(interfaces)
        
        if interfaces:
            if not self.settings.value('interface') or self.settings.value('interface') not in interfaces:
                self.settings.setValue('interface', list(interfaces)[0])
            self.interface_combo.setCurrentText(self.settings.value('interface'))
    
    def update_color_ui(self, mode):
        """根据颜色模式更新UI"""
        if mode == '三色模式':
            self.color_stacks.setCurrentIndex(0)
        elif mode == '渐变模式':
            self.color_stacks.setCurrentIndex(1)
        elif mode == '自定义分段模式':
            self.color_stacks.setCurrentIndex(2)
        elif mode == '速度映射模式':
            self.color_stacks.setCurrentIndex(3)
    
    def add_color_segment(self):
        """添加颜色分段"""
        row = self.segment_table.rowCount()
        self.segment_table.insertRow(row)
        
        # 阈值输入
        threshold = QSpinBox()
        threshold.setRange(0, 10000)
        self.segment_table.setCellWidget(row, 0, threshold)
        
        # 颜色按钮
        color_btn = QPushButton('选择颜色')
        color_btn.clicked.connect(lambda: self.choose_segment_color(row))
        self.segment_table.setCellWidget(row, 1, color_btn)
        
        # 删除按钮
        del_btn = QPushButton('删除')
        del_btn.clicked.connect(lambda: self.remove_segment(row))
        self.segment_table.setCellWidget(row, 2, del_btn)
    
    def choose_segment_color(self, row):
        """选择分段颜色"""
        color = QColorDialog.getColor()
        if color.isValid():
            btn = self.segment_table.cellWidget(row, 1)
            btn.setStyleSheet(f"background-color: {color.name()};")
            # 保存颜色到设置
    
    def remove_segment(self, row):
        """删除分段"""
        self.segment_table.removeRow(row)
    
    def monitor_speed(self):
        """监测网速的线程函数"""
        while True:
            current_stats = psutil.net_io_counters(pernic=True)
            current_time = time.time()
            time_diff = current_time - self.last_time
            
            for interface, stats in current_stats.items():
                if interface in self.last_stats:
                    last_stat = self.last_stats[interface]
                    bytes_sent = stats.bytes_sent - last_stat.bytes_sent
                    bytes_recv = stats.bytes_recv - last_stat.bytes_recv
                    
                    self.current_speeds[interface] = {
                        'upload': bytes_sent / time_diff,
                        'download': bytes_recv / time_diff,
                        'total': (bytes_sent + bytes_recv) / time_diff
                    }
            
            self.last_stats = current_stats
            self.last_time = current_time
            time.sleep(1)
    
    def update_history(self):
        """更新历史记录"""
        if not self.current_speeds:
            return
            
        # 计算总网速或单个网卡网速
        if self.settings.value('display_mode') == '总网速':
            total_up = sum(speed['upload'] for speed in self.current_speeds.values())
            total_down = sum(speed['download'] for speed in self.current_speeds.values())
        else:
            if self.settings.value('interface') in self.current_speeds:
                total_up = self.current_speeds[self.settings.value('interface')]['upload']
                total_down = self.current_speeds[self.settings.value('interface')]['download']
            else:
                total_up = total_down = 0
        
        # 转换为KB/s
        up_kb = total_up / 1024
        down_kb = total_down / 1024
        
        # 添加新记录
        now = datetime.now()
        self.history_data['time'].append(now)
        self.history_data['upload'].append(up_kb)
        self.history_data['download'].append(down_kb)
        
        # 保持记录数量不超过最大值
        if len(self.history_data['time']) > self.max_history_points:
            self.history_data['time'].pop(0)
            self.history_data['upload'].pop(0)
            self.history_data['download'].pop(0)
        
        # 更新图表
        self.update_history_graph()
    
    def update_history_graph(self):
        """更新历史图表"""
        if not self.history_data['time']:
            return
            
        scene = self.history_graph.scene()
        scene.clear()
        
        # 设置场景大小
        width = self.history_graph.width() - 20
        height = self.history_graph.height() - 20
        scene.setSceneRect(0, 0, width, height)
        
        # 计算最大速度用于缩放
        max_speed = max(max(self.history_data['upload']), max(self.history_data['download'])) if self.history_data['upload'] and self.history_data['download'] else 1
        max_speed = max(max_speed, 1)  # 确保不为0
        
        # 绘制坐标轴
        pen = QPen(Qt.black, 1)
        scene.addLine(50, height - 50, width - 50, height - 50, pen)  # X轴
        scene.addLine(50, height - 50, 50, 50, pen)  # Y轴
        
        # 添加刻度标记
        font = QFont('Arial', 8)
        
        # Y轴刻度
        for i in range(0, 11):
            y = height - 50 - (i * (height - 100) / 10)
            scene.addLine(45, y, 50, y, pen)
            text = scene.addText(f"{i * max_speed / 10:.1f}", font)
            text.setPos(10, y - 10)
        
        # X轴刻度 (时间)
        time_count = len(self.history_data['time'])
        step = max(1, time_count // 10)

        # 防御性编程：确保time_count-1不为零
        if time_count <= 1:
            # 只有一个数据点时，直接放在中间
            x = width / 2
            scene.addLine(x, height - 50, x, height - 45, pen)
            time_str = self.history_data['time'][0].strftime("%H:%M")
            text = scene.addText(time_str, font)
            text.setPos(x - 15, height - 40)
        else:
            for i in range(0, time_count, step):
                if i >= time_count:
                    continue
                
                x = 50 + (width - 100) * i / (time_count - 1)
                scene.addLine(x, height - 50, x, height - 45, pen)
                
                time_str = self.history_data['time'][i].strftime("%H:%M")
                text = scene.addText(time_str, font)
                text.setPos(x - 15, height - 40)
        
        # 绘制上传速度曲线
        if len(self.history_data['time']) > 1:
            upload_path = QPainterPath()
            upload_path.moveTo(50, height - 50 - (self.history_data['upload'][0] / max_speed * (height - 100)))
            
            for i in range(1, len(self.history_data['time'])):
                x = 50 + (width - 100) * i / (time_count - 1)
                y = height - 50 - (self.history_data['upload'][i] / max_speed * (height - 100))
                upload_path.lineTo(x, y)
            
            scene.addPath(upload_path, QPen(Qt.blue, 2))
        
        # 绘制下载速度曲线
        if len(self.history_data['time']) > 1:
            download_path = QPainterPath()
            download_path.moveTo(50, height - 50 - (self.history_data['download'][0] / max_speed * (height - 100)))
            
            for i in range(1, len(self.history_data['time'])):
                x = 50 + (width - 100) * i / (time_count - 1)
                y = height - 50 - (self.history_data['download'][i] / max_speed * (height - 100))
                download_path.lineTo(x, y)
            
            scene.addPath(download_path, QPen(Qt.red, 2))
        
        # 添加图例
        upload_legend = scene.addRect(60, 20, 15, 15, QPen(Qt.blue), QBrush(Qt.blue))
        upload_text = scene.addText("上传速度", font)
        upload_text.setPos(80, 15)
        
        download_legend = scene.addRect(60, 40, 15, 15, QPen(Qt.red), QBrush(Qt.red))
        download_text = scene.addText("下载速度", font)
        download_text.setPos(80, 35)
    
    def update_display(self):
        """更新显示"""
        if not self.current_speeds:
            return
            
        # 计算总网速或单个网卡网速
        if self.settings.value('display_mode') == '总网速':
            total_up = sum(speed['upload'] for speed in self.current_speeds.values())
            total_down = sum(speed['download'] for speed in self.current_speeds.values())
            total_speed = total_up + total_down
        else:
            if self.settings.value('interface') in self.current_speeds:
                total_up = self.current_speeds[self.settings.value('interface')]['upload']
                total_down = self.current_speeds[self.settings.value('interface')]['download']
                total_speed = total_up + total_down
            else:
                total_up = total_down = total_speed = 0
        
        # 确定显示内容
        display_content = self.settings.value('display_content')
        if display_content == '上传+下载':
            speed_value = total_speed
            up_value, up_unit = self.convert_speed(total_up, self.settings.value('unit'))
            down_value, down_unit = self.convert_speed(total_down, self.settings.value('unit'))
            display_text = f"🔺{up_value:.1f}{up_unit if self.settings.value('show_unit') else ''} 🔻{down_value:.1f}{down_unit if self.settings.value('show_unit') else ''}"
        elif display_content == '仅上传':
            speed_value = total_up
            up_value, up_unit = self.convert_speed(total_up, self.settings.value('unit'))
            display_text = f"🔺{up_value:.1f}{up_unit if self.settings.value('show_unit') else ''}"
        else:  # 仅下载
            speed_value = total_down
            down_value, down_unit = self.convert_speed(total_down, self.settings.value('unit'))
            display_text = f"🔻{down_value:.1f}{down_unit if self.settings.value('show_unit') else ''}"
        
        # 转换单位
        value, unit_str = self.convert_speed(speed_value, self.settings.value('unit'))
        
        # 确定颜色
        speed_kb = speed_value / 1024  # 转换为KB/s
        color = self.get_speed_color(speed_kb)
        
        # 确保color有效
        if not color or not isinstance(color, QColor):
            color = QColor(0, 0, 0)  # 默认黑色

        # 更新主窗口显示
        self.speed_label.setText(display_text)
        self.speed_label.setStyleSheet(f"font-size: {self.settings.value('font_size')}px; color: {color.name()};")
        
        # 更新任务栏标题
        if self.settings.value('show_taskbar', True, type=bool):
            # 强制更新窗口标题的技巧
            current_title = self.windowTitle()
            if current_title:
                self.setWindowTitle("")  # 先清空标题
                QApplication.processEvents()  # 强制处理事件队列
            self.setWindowTitle(f"网速监测 - {display_text}")
            # 确保窗口标题真正更新
            self.setWindowFlags(self.windowFlags() | Qt.WindowTitleHint)
            self.show()
        else:
            self.setWindowTitle(f'网速监测工具 - 增强版 v{__version__}')
        
        # 更新任务栏显示
        if self.settings.value('show_taskbar', True, type=bool):
            if not hasattr(self, 'taskbar_window'):
                self.init_taskbar()
            
            # 设置任务栏标签文本
            self.taskbar_label.setText(display_text)
            self.taskbar_label.setStyleSheet(f"""
                QLabel {{
                    color: {color.name()};
                    font-size: {self.settings.value('font_size')}px;
                    padding: 0 5px;
                }}
            """)
            
            # 确保窗口可见
            if not self.taskbar_window.isVisible():
                self.taskbar_window.show()
            
            # 更新任务栏窗口位置
            self.update_taskbar_position()
        elif hasattr(self, 'taskbar_window'):
            self.taskbar_window.hide()

        # 更新所有浮动窗口显示
        for monitor_index, floating_window in self.floating_windows.items():
            floating_window.update_speed(
                display_text, 
                color, 
                self.settings.value('font_size'),
                self.history_data['upload'][-30:] if self.history_data['upload'] else [],
                self.history_data['download'][-30:] if self.history_data['download'] else [],
                self.settings.value('float_show_mini_graph', True, type=bool),
                self.settings.value('float_show_upload', True, type=bool),
                self.settings.value('float_show_download', True, type=bool),
                self.settings.value('float_show_total', True, type=bool),
                self.settings.value('float_show_unit', True, type=bool)
            )
    
    def get_speed_color(self, speed_kb):
        """根据速度获取颜色"""
        # 确保默认颜色
        default_color = QColor(0, 0, 0)  # 默认黑色
        
        try:
            color_mode = self.settings.value('color_mode')
            
            if color_mode == '三色模式':
                slow_color = self.settings.value('slow_color', QColor(0, 255, 0))
                medium_color = self.settings.value('medium_color', QColor(255, 255, 0))
                fast_color = self.settings.value('fast_color', QColor(255, 0, 0))
                
                if not all([slow_color, medium_color, fast_color]):
                    return default_color
                    
                if speed_kb < self.settings.value('slow_threshold', 100, type=int):
                    return slow_color
                elif speed_kb < self.settings.value('fast_threshold', 1000, type=int):
                    return medium_color
                else:
                    return fast_color
            
            elif color_mode == '渐变模式':
                start_color = self.settings.value('gradient_start', QColor(0, 255, 0))
                end_color = self.settings.value('gradient_end', QColor(255, 0, 0))
                
                if not start_color or not end_color:
                    return default_color
                    
                max_speed = self.settings.value('max_speed', 1000, type=int)
                ratio = min(speed_kb / max_speed, 1.0)
                
                red = start_color.red() + (end_color.red() - start_color.red()) * ratio
                green = start_color.green() + (end_color.green() - start_color.green()) * ratio
                blue = start_color.blue() + (end_color.blue() - start_color.blue()) * ratio
                
                return QColor(int(red), int(green), int(blue))
            
            elif color_mode == '自定义分段模式':
                return QColor(0, 0, 255)  # 默认蓝色
            
            elif color_mode == '速度映射模式':
                return QColor(0, 0, 255)  # 默认蓝色
            
        except Exception as e:
            print(f"获取颜色错误: {e}")
        
        return default_color

    


    def convert_speed(self, speed_bps, unit_pref):
        """转换网速单位"""
        if unit_pref == '自动选择':
            if speed_bps < 1024:
                return speed_bps, 'B/s'
            elif speed_bps < 1024 * 1024:
                return speed_bps / 1024, 'KB/s'
            else:
                return speed_bps / (1024 * 1024), 'MB/s'
        elif unit_pref == 'bps':
            return speed_bps * 8, 'bps'
        elif unit_pref == 'Kbps':
            return speed_bps * 8 / 1024, 'Kbps'
        elif unit_pref == 'Mbps':
            return speed_bps * 8 / (1024 * 1024), 'Mbps'
        elif unit_pref == 'B/s':
            return speed_bps, 'B/s'
        elif unit_pref == 'KB/s':
            return speed_bps / 1024, 'KB/s'
        elif unit_pref == 'MB/s':
            return speed_bps / (1024 * 1024), 'MB/s'
        else:
            return speed_bps / 1024, 'KB/s'
    
    def choose_color(self, color_type):
        """选择颜色"""
        color = QColorDialog.getColor()
        if color.isValid():
            if color_type == 'slow':
                self.settings.setValue('slow_color', color)
                self.slow_color_btn.setStyleSheet(f"background-color: {color.name()};")
            elif color_type == 'medium':
                self.settings.setValue('medium_color', color)
                self.medium_color_btn.setStyleSheet(f"background-color: {color.name()};")
            elif color_type == 'fast':
                self.settings.setValue('fast_color', color)
                self.fast_color_btn.setStyleSheet(f"background-color: {color.name()};")
            elif color_type == 'gradient_start':
                self.settings.setValue('gradient_start', color)
                self.start_color_btn.setStyleSheet(f"background-color: {color.name()};")
            elif color_type == 'gradient_end':
                self.settings.setValue('gradient_end', color)
                self.end_color_btn.setStyleSheet(f"background-color: {color.name()};")
            elif color_type == 'map_start':
                self.settings.setValue('map_start', color)
                self.map_start_color_btn.setStyleSheet(f"background-color: {color.name()};")
            elif color_type == 'map_end':
                self.settings.setValue('map_end', color)
                self.map_end_color_btn.setStyleSheet(f"background-color: {color.name()};")
    
    def _autosave_settings(self):
        """设置变更防抖自动保存（500ms）"""
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        self._settings_save_timer.start(500)
    
    def _connect_autosave(self):
        """连接所有设置控件变更信号 → 自动保存"""
        # 网络设置
        self.interface_combo.currentTextChanged.connect(self._autosave_settings)
        self.display_mode_combo.currentTextChanged.connect(self._autosave_settings)
        self.display_content_combo.currentTextChanged.connect(self._autosave_settings)
        self.unit_combo.currentTextChanged.connect(self._autosave_settings)
        self.show_unit_check.stateChanged.connect(self._autosave_settings)
        
        # 显示设置
        self.font_size.valueChanged.connect(self._autosave_settings)
        self.taskbar_check.stateChanged.connect(self._autosave_settings)
        self.float_check.stateChanged.connect(self._autosave_settings)
        
        # 每个显示器的浮动窗口设置
        for i in range(len(self.get_all_monitors())):
            position_combo = self.findChild(QComboBox, f'position_combo_{i}')
            x_pos = self.findChild(QSpinBox, f'x_pos_{i}')
            y_pos = self.findChild(QSpinBox, f'y_pos_{i}')
            opacity = self.findChild(QDoubleSpinBox, f'float_opacity_{i}')
            if position_combo:
                position_combo.currentTextChanged.connect(self._autosave_settings)
            if x_pos:
                x_pos.valueChanged.connect(self._autosave_settings)
            if y_pos:
                y_pos.valueChanged.connect(self._autosave_settings)
            if opacity:
                opacity.valueChanged.connect(self._autosave_settings)
        
        # 浮动窗口显示选项
        self.float_show_mini_graph.stateChanged.connect(self._autosave_settings)
        self.float_show_upload.stateChanged.connect(self._autosave_settings)
        self.float_show_download.stateChanged.connect(self._autosave_settings)
        self.float_show_total.stateChanged.connect(self._autosave_settings)
        self.float_show_unit.stateChanged.connect(self._autosave_settings)
        
        # 颜色设置
        self.color_mode_combo.currentTextChanged.connect(self._autosave_settings)
        self.color_unit_combo.currentTextChanged.connect(self._autosave_settings)
        self.slow_threshold.valueChanged.connect(self._autosave_settings)
        self.fast_threshold.valueChanged.connect(self._autosave_settings)
        self.max_speed_spin.valueChanged.connect(self._autosave_settings)
        self.map_speed_spin.valueChanged.connect(self._autosave_settings)
        
        # 行为设置
        self.startup_check.stateChanged.connect(self._autosave_settings)
        self.start_minimized_check.stateChanged.connect(self._autosave_settings)
        self.minimize_location_combo.currentTextChanged.connect(self._autosave_settings)
        self.close_action_combo.currentTextChanged.connect(self._autosave_settings)
        
        # Web服务器设置
        self.web_enable_check.stateChanged.connect(self._autosave_settings)
        self.web_port_spin.valueChanged.connect(self._autosave_settings)
        
        # 历史记录设置
        self.history_duration.valueChanged.connect(self._autosave_settings)
        self.history_interval.valueChanged.connect(self._autosave_settings)
    
    def _save_settings_now(self):
        """立即保存所有设置到 QSettings（实时自动保存核心，防抖后/退出时调用）"""
        # 保存网络设置
        self.settings.setValue('interface', self.interface_combo.currentText())
        self.settings.setValue('display_mode', self.display_mode_combo.currentText())
        self.settings.setValue('display_content', self.display_content_combo.currentText())
        self.settings.setValue('unit', self.unit_combo.currentText())
        self.settings.setValue('show_unit', self.show_unit_check.isChecked())
        
        # 保存显示设置
        self.settings.setValue('font_size', self.font_size.value())
        self.settings.setValue('show_taskbar', self.taskbar_check.isChecked())
        self.settings.setValue('show_floating', self.float_check.isChecked())
        
        # 转换单位后保存阈值
        self.settings.setValue('color_unit', self.color_unit_combo.currentText())
        self.settings.setValue('slow_threshold', self.convert_color_threshold(self.slow_threshold.value()))
        self.settings.setValue('fast_threshold', self.convert_color_threshold(self.fast_threshold.value()))
        self.settings.setValue('max_speed', self.convert_color_threshold(self.max_speed_spin.value()))
        self.settings.setValue('map_speed', self.convert_color_threshold(self.map_speed_spin.value()))
    

        # 保存每个显示器的浮动窗口设置
        monitors = self.get_all_monitors()
        for i, monitor in enumerate(monitors):
            position_combo = self.findChild(QComboBox, f'position_combo_{i}')
            x_pos = self.findChild(QSpinBox, f'x_pos_{i}')
            y_pos = self.findChild(QSpinBox, f'y_pos_{i}')
            opacity = self.findChild(QDoubleSpinBox, f'float_opacity_{i}')
            
            if position_combo:
                self.settings.setValue(f'display_position_{i}', position_combo.currentText())
            if x_pos:
                self.settings.setValue(f'custom_x_{i}', x_pos.value())
            if y_pos:
                self.settings.setValue(f'custom_y_{i}', y_pos.value())
            if opacity:
                self.settings.setValue(f'float_opacity_{i}', opacity.value())
        
        # 保存浮动窗口显示选项
        self.settings.setValue('float_show_mini_graph', self.float_show_mini_graph.isChecked())
        self.settings.setValue('float_show_upload', self.float_show_upload.isChecked())
        self.settings.setValue('float_show_download', self.float_show_download.isChecked())
        self.settings.setValue('float_show_total', self.float_show_total.isChecked())
        self.settings.setValue('float_show_unit', self.float_show_unit.isChecked())
        
        # 保存颜色设置
        self.settings.setValue('color_mode', self.color_mode_combo.currentText())
        self.settings.setValue('slow_threshold', self.slow_threshold.value())
        self.settings.setValue('fast_threshold', self.fast_threshold.value())
        self.settings.setValue('max_speed', self.max_speed_spin.value())
        self.settings.setValue('map_speed', self.map_speed_spin.value())
        
        # 保存行为设置
        self.settings.setValue('startup', self.startup_check.isChecked())
        self.settings.setValue('start_minimized', self.start_minimized_check.isChecked())
        self.settings.setValue('minimize_location', self.minimize_location_combo.currentText())
        self.settings.setValue('close_action', self.close_action_combo.currentText())
        
        # 保存Web服务器设置
        self.settings.setValue('web_enable', self.web_enable_check.isChecked())
        self.settings.setValue('web_port', self.web_port_spin.value())
        
        # 保存历史记录设置
        self.settings.setValue('history_duration', self.history_duration.value())
        self.settings.setValue('history_interval', self.history_interval.value())
    
    def apply_settings(self):
        """应用所有设置（保存设置 + 应用运行时效果）"""
        self._save_settings_now()
        
        # 重新计算历史记录点数
        self.max_history_points = self.history_duration.value() * 3600 / self.history_interval.value()
        
        # 应用设置
        self.set_auto_start(self.startup_check.isChecked())
        
        # 更新Web服务器
        web_enable = self.web_enable_check.isChecked()
        if web_enable:
            self.start_web_server()
        elif self.web_server:
            self.web_server.shutdown()
            self.web_server = None
        
        # 更新浮动窗口
        self.init_floating_windows()
        if self.float_check.isChecked():
            for window in self.floating_windows.values():
                window.show()
        else:
            for window in self.floating_windows.values():
                window.hide()
        
        # 更新任务栏显示
        if self.taskbar_check.isChecked():
            self.init_taskbar()
            self.taskbar_window.show()
        elif hasattr(self, 'taskbar_window'):
            self.taskbar_window.hide()
        
        QMessageBox.information(self, '提示', '设置已应用!')
    
    def toggle_floating_display(self, state):
        """切换浮动窗口显示状态"""
        self.settings.setValue('show_floating', state == Qt.Checked)
        if state == Qt.Checked:
            for window in self.floating_windows.values():
                window.show()
        else:
            for window in self.floating_windows.values():
                window.hide()
    
    def restore_defaults(self):
        """恢复默认设置"""
        reply = QMessageBox.question(self, '确认', '确定要恢复所有默认设置吗?', 
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # 重置网络设置
            self.interface_combo.setCurrentIndex(0)
            self.display_mode_combo.setCurrentIndex(0)
            self.display_content_combo.setCurrentIndex(0)
            self.unit_combo.setCurrentIndex(0)
            self.show_unit_check.setChecked(True)
            
            # 重置显示设置
            self.font_size.setValue(12)
            self.taskbar_check.setChecked(True)
            self.float_check.setChecked(False)
            
            # 重置浮动窗口设置
            monitors = self.get_all_monitors()
            for i, monitor in enumerate(monitors):
                position_combo = self.findChild(QComboBox, f'position_combo_{i}')
                x_pos = self.findChild(QSpinBox, f'x_pos_{i}')
                y_pos = self.findChild(QSpinBox, f'y_pos_{i}')
                opacity = self.findChild(QDoubleSpinBox, f'float_opacity_{i}')
                
                position_combo.setCurrentIndex(3)  # 右下角
                x_pos.setValue(0)
                y_pos.setValue(0)
                opacity.setValue(0.9)
            
            # 重置浮动窗口显示选项
            self.float_show_mini_graph.setChecked(True)
            self.float_show_upload.setChecked(True)
            self.float_show_download.setChecked(True)
            self.float_show_total.setChecked(True)
            self.float_show_unit.setChecked(True)
            
            # 重置颜色设置
            self.color_mode_combo.setCurrentIndex(0)
            self.slow_threshold.setValue(100)
            self.fast_threshold.setValue(1000)
            self.max_speed_spin.setValue(1000)
            self.map_speed_spin.setValue(100)
            
            # 重置行为设置
            self.startup_check.setChecked(False)
            self.start_minimized_check.setChecked(False)
            self.minimize_location_combo.setCurrentIndex(1)
            self.close_action_combo.setCurrentIndex(1)
            
            # 重置Web服务器设置
            self.web_enable_check.setChecked(False)
            self.web_port_spin.setValue(8080)
            
            # 重置历史记录设置
            self.history_duration.setValue(6)
            self.history_interval.setValue(5)
            
            QMessageBox.information(self, '提示', '已恢复默认设置!')
    
    def update_floating_position(self, window, monitor, position):
        """更新浮动窗口位置"""
        work_area = monitor['work_area']
        screen_width = work_area[2] - work_area[0]
        screen_height = work_area[3] - work_area[1]
        
        if position == '左上角':
            x, y = work_area[0], work_area[1]
        elif position == '右上角':
            x = work_area[2] - window.width()
            y = work_area[1]
        elif position == '左下角':
            x = work_area[0]
            y = work_area[3] - window.height()
        elif position == '右下角':
            x = work_area[2] - window.width()
            y = work_area[3] - window.height()
        else:  # 自定义位置
            x = work_area[0] + self.settings.value(f'custom_x_{monitor["index"]}', 0, type=int)
            y = work_area[1] + self.settings.value(f'custom_y_{monitor["index"]}', 0, type=int)
        
        window.move(x, y)
    
    def show_normal(self):
        """从托盘恢复显示"""
        self.show()
        self.setWindowState(Qt.WindowNoState)
    
    def tray_icon_clicked(self, reason):
        """托盘图标点击事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()
    
    def close_app(self):
        """退出应用程序"""
        # 停止自动保存定时器并强制保存设置与窗口几何
        if hasattr(self, '_settings_save_timer'):
            self._settings_save_timer.stop()
        self._save_settings_now()
        self.settings.setValue('window_geometry', bytes(self.saveGeometry().toBase64()).decode('utf-8'))
        self.settings.setValue('window_maximized', self.isMaximized())
        
        # 关闭所有浮动窗口
        for window in self.floating_windows.values():
            window.close()
        
        # 关闭Web服务器
        if self.web_server:
            self.web_server.shutdown()
        
        # 关闭任务栏窗口（如果存在）
        if hasattr(self, 'taskbar_window'):
            self.taskbar_window.close()
        
        # 隐藏系统托盘图标
        self.tray_icon.hide()
        
        # 退出应用程序
        QApplication.quit()



    
    def toggle_taskbar_display(self, state):
        """切换任务栏显示状态"""
        self.settings.setValue('show_taskbar', state == Qt.Checked)
        # 立即更新显示
        if state == Qt.Checked:
            if not hasattr(self, 'taskbar_window'):
                self.init_taskbar()
            self.taskbar_window.show()
            self.update_display()  # 立即更新显示
        else:
            if hasattr(self, 'taskbar_window'):
                self.taskbar_window.hide()
            self.setWindowTitle(f'网速监测工具 - 增强版 v{__version__}')
            self.show()  # 确保窗口可见

    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止自动保存定时器并强制保存设置
        if hasattr(self, '_settings_save_timer'):
            self._settings_save_timer.stop()
        self._save_settings_now()
        
        close_action = self.settings.value('close_action')
        
        if close_action == '最小化到任务栏':
            event.ignore()
            self.showMinimized()
        elif close_action == '最小化到托盘':
            event.ignore()
            self.hide()
            self.tray_icon.showMessage('网速监测', '程序已最小化到托盘', QSystemTrayIcon.Information, 2000)
        else:  # 直接退出
            self.close_app()

class FloatingWindow(QWidget):
    """浮动显示窗口"""
    def __init__(self, monitor_index):
        super().__init__()
        self.monitor_index = monitor_index
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        self.speed_text = '0 KB/s'
        self.color = QColor(0, 0, 0)
        self.font_size = 12
        self.upload_data = []
        self.download_data = []
        self.show_mini_graph = True
        self.show_upload = True
        self.show_download = True
        self.show_total = True
        self.show_unit = True
        
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet('background-color: rgba(0, 0, 0, 0);')
        
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)
        
        self.resize(200, 80)
        
        # 用于调整大小的边框
        self.resize_handle_size = 8
        self.is_resizing = False
        self.resize_start_pos = None
        self.resize_start_geometry = None
    
    def update_speed(self, text, color, font_size, upload_data, download_data, 
                    show_mini_graph, show_upload, show_download, show_total, show_unit):
        """更新显示的速度"""
        self.speed_text = text
        self.color = color
        self.font_size = font_size
        self.upload_data = upload_data
        self.download_data = download_data
        self.show_mini_graph = show_mini_graph
        self.show_upload = show_upload
        self.show_download = show_download
        self.show_total = show_total
        self.show_unit = show_unit
        
        self.label.setText(text)
        
        # 根据设置调整样式
        style = f"""
            color: {color.name()};
            font-size: {font_size}px;
            background-color: rgba(240, 240, 240, 180);
            border-radius: 5px;
            padding: 5px;
        """
        
        if self.show_mini_graph and (self.upload_data or self.download_data):
            style += "min-width: 180px; min-height: 60px;"
        
        self.label.setStyleSheet(style)
        
        # 如果需要显示迷你图表，则重绘
        if self.show_mini_graph and (self.upload_data or self.download_data):
            self.update()
    
    def paintEvent(self, event):
        """绘制迷你图表"""
        super().paintEvent(event)
        
        # 防御性编程：检查是否有数据可绘制
        if not self.show_mini_graph or not (self.upload_data or self.download_data):
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制迷你图表背景
        chart_rect = QRectF(10, 10, self.width() - 20, self.height() - 20)
        painter.fillRect(chart_rect, QBrush(QColor(240, 240, 240, 180)))
        
        # 计算最大速度用于缩放
        max_speed = max(max(self.upload_data) if self.upload_data else 0, 
                    max(self.download_data) if self.download_data else 0)
        max_speed = max(max_speed, 1)  # 确保不为0
        
        # 绘制上传速度曲线
        if self.show_upload and self.upload_data:
            pen = QPen(QColor(0, 0, 255, 200), 1)
            painter.setPen(pen)
            
            points = []
            # 防御性编程：确保除数不为零
            data_len = len(self.upload_data)
            if data_len <= 1:
                # 只有一个数据点时，放在中间位置
                x = self.width() / 2
                y = self.height() - 10 - (self.upload_data[0] / max_speed * (self.height() - 30))
                points.append(QPointF(x, y))
            else:
                for i, speed in enumerate(self.upload_data):
                    x = 10 + (self.width() - 20) * i / (data_len - 1)
                    y = self.height() - 10 - (speed / max_speed * (self.height() - 30))
                    points.append(QPointF(x, y))
            
            if points:
                painter.drawPolyline(QPolygonF(points))
        
        # 绘制下载速度曲线
        if self.show_download and self.download_data:
            pen = QPen(QColor(255, 0, 0, 200), 1)
            painter.setPen(pen)
            
            points = []
            # 防御性编程：确保除数不为零
            data_len = len(self.download_data)
            if data_len <= 1:
                # 只有一个数据点时，放在中间位置
                x = self.width() / 2
                y = self.height() - 10 - (self.download_data[0] / max_speed * (self.height() - 30))
                points.append(QPointF(x, y))
            else:
                for i, speed in enumerate(self.download_data):
                    x = 10 + (self.width() - 20) * i / (data_len - 1)
                    y = self.height() - 10 - (speed / max_speed * (self.height() - 30))
                    points.append(QPointF(x, y))
            
            if points:
                painter.drawPolyline(QPolygonF(points))

    
    def mousePressEvent(self, event):
        """鼠标按下事件，实现拖动和调整大小"""
        if event.button() == Qt.LeftButton:
            # 检查是否点击了调整大小的区域
            if (self.width() - event.pos().x() < self.resize_handle_size and 
                self.height() - event.pos().y() < self.resize_handle_size):
                self.is_resizing = True
                self.resize_start_pos = event.globalPos()
                self.resize_start_geometry = self.geometry()
            else:
                self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件，实现拖动和调整大小"""
        if event.buttons() == Qt.LeftButton:
            if self.is_resizing:
                # 调整窗口大小
                delta = event.globalPos() - self.resize_start_pos
                new_width = max(100, self.resize_start_geometry.width() + delta.x())
                new_height = max(50, self.resize_start_geometry.height() + delta.y())
                self.setGeometry(
                    self.resize_start_geometry.x(),
                    self.resize_start_geometry.y(),
                    new_width,
                    new_height
                )
            else:
                # 移动窗口
                self.move(event.globalPos() - self.drag_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            self.is_resizing = False
            event.accept()
    
    def contextMenuEvent(self, event):
        """右键菜单事件"""
        menu = QMenu(self)
        
        close_action = menu.addAction("关闭")
        close_action.triggered.connect(self.close)
        
        menu.exec_(event.globalPos())

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置中文显示
    font = QFont('Microsoft YaHei', 9)
    app.setFont(font)
    
    monitor = SpeedMonitor()
    
    # 根据设置决定初始显示方式
    if not monitor.settings.value('start_minimized', False, type=bool):
        monitor.show()
        # 恢复最大化状态
        if monitor.settings.value('window_maximized', False, type=bool):
            monitor.showMaximized()
    
    sys.exit(app.exec_())