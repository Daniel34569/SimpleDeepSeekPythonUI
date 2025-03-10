import os
import json
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QSplitter, QHBoxLayout, QVBoxLayout,
                             QLineEdit, QTextEdit, QPushButton, QLabel, QListWidget, QListWidgetItem,
                             QGroupBox, QFileDialog, QMessageBox, QDialog, QSpinBox, QDoubleSpinBox,
                             QRadioButton, QButtonGroup, QMenu, QInputDialog, QCheckBox)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QColor
import tiktoken
from openai import OpenAI
from openai.types.chat import ChatCompletion

class ConfigManager:
    CONFIG_FILE = "config.json"
    
    @classmethod
    def load_config(cls):
        try:
            with open(cls.CONFIG_FILE, 'r') as f:
                config = json.load(f)
                if 'conversations' in config and config['conversations']:
                    if isinstance(config['conversations'][0], str):
                        new_conv_list = []
                        for conv_id in config['conversations']:
                            new_conv_list.append({
                                'id': conv_id,
                                'name': f"Conversation {conv_id}",
                                'file': f"log/{conv_id}.txt"
                            })
                        config['conversations'] = new_conv_list
                else:
                    config['conversations'] = []
                if 'history_limit' not in config:
                    config['history_limit'] = 10
                if 'use_timestamp' not in config:
                    config['use_timestamp'] = True
                return config
        except FileNotFoundError:
            return cls.load_default_config()
        except Exception as e:
            QMessageBox.warning(None, "Error", f"Can't Read Config: {str(e)}")
            return cls.load_default_config()

    @classmethod
    def save_config(cls, config):
        try:
            with open(cls.CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            QMessageBox.warning(None, "Error", f"Can't Save Config: {str(e)}")

    @classmethod
    def load_default_config(cls):
        return {
            'api_key': '',
            'price_per_token': 0.02,
            'conversations': [],
            'history_limit': 10,
            'use_timestamp': True
        }


class DeepSeekUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client = None
        self.current_conversation = None
        self.conversations = {}
        self.config = ConfigManager.load_config()
        self.current_model = "v3"
        self.history_limit = self.config.get('history_limit', 10)
        self.use_timestamp = self.config.get('use_timestamp', True)
        self.initUI()
        self.load_conversations()
        self.setStyleSheet(self.get_stylesheet())
        self.prefix_input.setStyleSheet("background-color: #f8f8f8;")
        self.suffix_input.setStyleSheet("background-color: #f8f8f8;")
        self.drop_last_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6666;
            }
            QPushButton:hover {
                background-color: #ff4444;
            }
        """)
        self.setStyleSheet("""
            QTextEdit, QDoubleSpinBox {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 3px;
            }
            QPushButton#danger_btn {
                background-color: #ff4444;
                color: white;
                min-width: 120px;
            }
            QPushButton#danger_btn:hover {
                background-color: #cc0000;
            }
            QLabel[paramLabel="true"] {
                font-weight: bold;
            }
        """)
        self.drop_last_btn.setObjectName("danger_btn")
        for label in [self.findChild(QLabel, "prefixLabel"), 
                    self.findChild(QLabel, "suffixLabel"),
                    self.findChild(QLabel, "tempLabel")]:
            label.setProperty("paramLabel", "true")
        self.setup_autosave()
        
    def initUI(self):
        self.setWindowTitle('DeepSeek Client')
        self.setGeometry(100, 100, 1200, 800)

        main_splitter = QSplitter(Qt.Horizontal)
        left_panel = self.create_left_panel()
        center_panel = self.create_center_panel()
        right_panel = self.create_right_panel()

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(center_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([200, 600, 300])

        self.setCentralWidget(main_splitter)

        self.api_key_input.setText(self.config.get('api_key', ''))
        self.price_input.setText(str(self.config.get('price_per_token', 0.02)))

    def setup_autosave(self):
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_state)
        self.autosave_timer.start(30000)

    def save_state(self):
        config = {
            'api_key': self.api_key_input.text(),
            'price_per_token': float(self.price_input.text() or 0),
            'conversations': list(self.config.get('conversations', [])),
            'history_limit': self.history_limit,
            'use_timestamp': self.use_timestamp
        }
        ConfigManager.save_config(config)

    def closeEvent(self, event):
        self.save_state()
        super().closeEvent(event)

    def initialize_client(self):
        api_key = self.api_key_input.text()
        if api_key:
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )

    def create_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout()
        
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.show_settings)
        
        self.conversation_list = QListWidget()
        self.conversation_list.itemClicked.connect(self.load_conversation)
        self.conversation_list.itemDoubleClicked.connect(self.show_conversation_details)
        
        self.conversation_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conversation_list.customContextMenuRequested.connect(self.show_conversation_context_menu)
        
        new_btn = QPushButton("New Conversation")
        new_btn.clicked.connect(self.new_conversation)
        
        layout.addWidget(new_btn)
        layout.addWidget(settings_btn)
        layout.addWidget(self.conversation_list)
        panel.setLayout(layout)
        return panel

    def show_conversation_context_menu(self, pos):
        item = self.conversation_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu()
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        action = menu.exec_(self.conversation_list.mapToGlobal(pos))
        conv_id = item.data(Qt.UserRole)
        if action == rename_action:
            self.rename_conversation(conv_id)
        elif action == delete_action:
            self.delete_conversation(conv_id)

    def rename_conversation(self, conv_id):
        conv = self.conversations.get(conv_id)
        if not conv:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Conversation", "Enter new name:", text=conv.get('name', conv_id))
        if ok and new_name.strip():
            new_name = new_name.strip()
            old_file = conv['file']
            new_file = os.path.join("log", f"{new_name}.txt")
            try:
                if os.path.exists(old_file):
                    os.rename(old_file, new_file)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"無法重新命名檔案: {str(e)}")
                return
            conv['name'] = new_name
            conv['file'] = new_file
            for idx, item in enumerate(self.config.get('conversations', [])):
                if item['id'] == conv_id:
                    self.config['conversations'][idx]['name'] = new_name
                    self.config['conversations'][idx]['file'] = new_file
                    break
            self.update_conversation_list()
            self.save_state()
            QMessageBox.information(self, "Success", "Conversation renamed successfully.")

    def delete_conversation(self, conv_id):
        conv = self.conversations.get(conv_id)
        if not conv:
            return
        reply = QMessageBox.question(self, "Delete Conversation", f"Are you sure you want to delete conversation '{conv['name']}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                if os.path.exists(conv['file']):
                    os.remove(conv['file'])
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete log file: {str(e)}")
            self.conversations.pop(conv_id, None)
            new_conv_list = [item for item in self.config.get('conversations', []) if item['id'] != conv_id]
            self.config['conversations'] = new_conv_list
            if self.current_conversation and self.current_conversation['id'] == conv_id:
                self.current_conversation = None
            self.update_conversation_list()
            self.save_state()
            QMessageBox.information(self, "Deleted", "Conversation deleted successfully.")

    def create_center_panel(self):
        panel = QWidget()
        layout = QVBoxLayout()

        self.api_group = QGroupBox("API Settings")
        api_layout = QVBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter API Key")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        api_layout.addWidget(self.api_key_input)
        
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("Price per 1k tokens")
        api_layout.addWidget(self.price_input)
        self.api_group.setLayout(api_layout)
        self.api_group.setCheckable(True)
        self.api_group.setChecked(False)
        layout.addWidget(self.api_group)
        
        control_group = QWidget()
        ctrl_layout = QVBoxLayout()

        # ========== prefix / postfix area ==========
        prefix_layout = QHBoxLayout()
        prefix_label = QLabel("前缀:")
        prefix_label.setObjectName("prefixLabel")
        prefix_layout.addWidget(prefix_label)
        self.prefix_input = QTextEdit()
        self.prefix_input.setMaximumHeight(60)
        prefix_layout.addWidget(self.prefix_input)
        ctrl_layout.addLayout(prefix_layout)

        suffix_layout = QHBoxLayout()
        suffix_label = QLabel("後綴:")
        suffix_label.setObjectName("suffixLabel")
        suffix_layout.addWidget(suffix_label)
        self.suffix_input = QTextEdit()
        self.suffix_input.setMaximumHeight(60)
        suffix_layout.addWidget(self.suffix_input)
        ctrl_layout.addLayout(suffix_layout)

        param_layout = QHBoxLayout()
        
        temp_layout = QHBoxLayout()
        temp_label = QLabel("Temperature:")
        temp_label.setObjectName("tempLabel")
        temp_layout.addWidget(temp_label)
        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setRange(0.0, 2.0)
        self.temperature_input.setSingleStep(0.1)
        self.temperature_input.setValue(0.7)
        temp_layout.addWidget(self.temperature_input)
        param_layout.addLayout(temp_layout)

        param_layout.addStretch()
        
        self.drop_last_btn = QPushButton("刪除最近一次對話")
        self.drop_last_btn.clicked.connect(self.drop_last_conversation)
        param_layout.addWidget(self.drop_last_btn)

        ctrl_layout.addLayout(param_layout)

        ctrl_layout.addStretch(0)

        control_group.setLayout(ctrl_layout)
        layout.addWidget(control_group)
        
        # ========== Prompt Input / Output Area ==========
        input_output_splitter = QSplitter(Qt.Vertical)

        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("Enter your prompt here...")
        self.prompt_input.textChanged.connect(self.update_token_count)
        
        self.token_label = QLabel("Tokens: 0")
        
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_prompt)
        
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        
        self.usage_label = QLabel("Usage: 0 tokens | Cost: $0.00")
        
        input_output_splitter.addWidget(self.prompt_input)
        input_output_splitter.addWidget(self.token_label)
        input_output_splitter.addWidget(send_btn)
        input_output_splitter.addWidget(self.result_display)
        input_output_splitter.addWidget(self.usage_label)
        layout.addWidget(input_output_splitter, stretch=1)
        panel.setLayout(layout)
        return panel

    def create_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout()
        
        self.history_list = QListWidget()
        self.history_list.setMinimumWidth(250)
        
        layout.addWidget(QLabel("History Log"))
        self.history_list.setWordWrap(True)
        self.history_list.setSpacing(5)
        self.history_list.setStyleSheet("""
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #ddd;
                white-space: normal;
            }
            QListWidget::item:hover {
                background-color: #f0f0f0;
            }
        """)
        layout.addWidget(self.history_list)
        panel.setLayout(layout)
        return panel
        

    def calculate_tokens(self, text):
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception as e:
            print(f"Token Cal Error: {e}")
            return len(text) // 4

    def update_token_count(self):
        text = self.prompt_input.toPlainText()
        token_count = self.calculate_tokens(text)
        self.token_label.setText(f"Tokens: {token_count}")

    def actual_api_call(self, prompt):
        if not self.client:
            return "Error: API Client Uninitialized!!", 0

        try:
            temperature = self.temperature_input.value()
            messages = self.build_history_messages(prompt)

            if self.current_model == "v3":
                using_model = "deepseek-chat"
            elif self.current_model == "r1":
                using_model = "deepseek-reasoner"
            else:
                print(f"Model Should Be V3 or R1!!!")
                return
            print(f"using_model:{using_model}, messages:{messages}")
            response: ChatCompletion = self.client.chat.completions.create(
                model=using_model,
                messages=messages,
                stream=False,
                temperature=temperature
            )

            print(f"Response:{response}")

            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content
                usage = response.usage.total_tokens if response.usage else 0
                return content, usage
            return "Error: Invalid API response", 0

        except Exception as e:
            return f"API Error: {str(e)}", 0

    def build_history_messages(self, new_prompt):
        messages = []
        if self.current_conversation:
            for entry in self.current_conversation['history'][-self.history_limit:]:
                messages.append({"role": "user", "content": entry['prompt']})
                messages.append({"role": "assistant", "content": entry['response']})
        messages.append({"role": "user", "content": new_prompt})
        return messages

    def drop_last_conversation(self):
        if not self.current_conversation or len(self.current_conversation['history']) == 0:
            QMessageBox.warning(self, "Failed", "No history to delete")
            return

        self.current_conversation['history'].pop()
        self.rewrite_conversation_file()
        self.update_history_list()
        QMessageBox.information(self, "Success", "已刪除最近一次對話紀錄")

    def rewrite_conversation_file(self):
        if not self.current_conversation:
            return
        
        try:
            with open(self.current_conversation['file'], 'w', encoding="utf-8-sig") as f:
                for entry in self.current_conversation['history']:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            QMessageBox.warning(self, "Failed", f"無法更新對話紀錄文件: {str(e)}")

    def update_history_list(self):
        self.history_list.clear()
        if self.current_conversation:
            for entry in self.current_conversation['history']:
                user_item = QListWidgetItem(f"👤 {entry['prompt'][:50]}...")
                user_item.setBackground(QColor(240, 240, 240))
                user_item.setData(Qt.UserRole, entry)
                self.history_list.addItem(user_item)
                self.adjust_item_height(user_item)
                
                assistant_item = QListWidgetItem(f"🤖 {entry['response'][:50]}...")
                assistant_item.setData(Qt.UserRole, entry)
                self.history_list.addItem(assistant_item)
                self.adjust_item_height(assistant_item)

    def adjust_item_height(self, item):
        list_width = self.history_list.width() - 20

        document = item.listWidget().fontMetrics()
        text = item.text()
        text_width = document.boundingRect(0, 0, list_width, 0, Qt.TextWordWrap, text).width()
        text_height = document.boundingRect(0, 0, list_width, 0, Qt.TextWordWrap, text).height()

        line_height = document.lineSpacing()
        num_lines = max(1, int(text_height / line_height))

        item.setSizeHint(QSize(list_width, num_lines * (line_height + 10) + 10))

    def send_prompt(self):
        self.initialize_client()
        
        if not self.client or not self.client.api_key:
            self.result_display.setText("Error: Please enter valid API Key")
            return

        prompt = self.prompt_input.toPlainText()
        prefix = self.prefix_input.toPlainText()
        suffix = self.suffix_input.toPlainText()
        full_prompt = f"{prefix}{prompt}{suffix}"
        if not full_prompt:
            self.result_display.setText("Error: Prompt Can't be empty")
            return

        response, usage = self.actual_api_call(full_prompt)
        
        self.result_display.setText(response)
        self.update_usage(usage)
        
        if self.current_conversation:
            self.save_conversation(full_prompt, response, usage)
            self.update_history_list()

    def update_usage(self, usage):
        try:
            price = float(self.price_input.text()) if self.price_input.text() else 0.0
        except:
            price = 0.0
        cost = (usage / 1000) * price
        self.usage_label.setText(f"Usage: {usage} tokens | Cost: ${cost:.4f}")

    def new_conversation(self):
        conv_id = str(int(time.time()))
        if self.use_timestamp:
            new_name = f"Conversation {conv_id}"
        else:
            new_name, ok = QInputDialog.getText(self, "New Conversation Name", "Enter conversation name:")
            if not ok or not new_name.strip():
                return
            new_name = new_name.strip()
        conv_data = {
            'id': conv_id,
            'name': new_name,
            'file': os.path.join("log", f"{new_name}.txt"),
            'history': []
        }
        self.current_conversation = conv_data
        self.conversations[conv_id] = conv_data
        self.config.setdefault('conversations', []).append({
            'id': conv_id,
            'name': conv_data['name'],
            'file': conv_data['file']
        })
        self.update_conversation_list()

    def save_conversation(self, prompt, response, usage):
        entry = {
            'prompt': prompt,
            'response': response,
            'usage': usage,
            'timestamp': time.time()
        }
        self.current_conversation['history'].append(entry)
        
        os.makedirs("log", exist_ok=True)
        with open(self.current_conversation['file'], 'a', encoding='utf-8-sig') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.save_state()

    def load_conversations(self):
        for conv_item in self.config.get('conversations', []):
            conv_id = conv_item['id']
            file_path = conv_item.get('file', f"log/{conv_id}.txt")
            if os.path.exists(file_path):
                self.conversations[conv_id] = {
                    'id': conv_id,
                    'name': conv_item.get('name', f"Conversation {conv_id}"),
                    'file': file_path,
                    'history': self.load_conversation_history(conv_id)
                }
        self.update_conversation_list()

    def update_conversation_list(self):
        self.conversation_list.clear()
        for conv in self.conversations.values():
            display_text = conv.get('name', conv['id'])
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, conv['id'])
            self.conversation_list.addItem(item)

    def load_conversation(self, item):
        conv_id = item.data(Qt.UserRole)
        self.current_conversation = self.conversations[conv_id]
        if self.current_conversation:
            if not self.current_conversation['history']:
                self.current_conversation['history'] = self.load_conversation_history(conv_id)
            
            self.update_history_list()

    def load_conversation_history(self, conv_id):
        history = []
        conv = self.conversations.get(conv_id)
        file_path = conv['file'] if conv else f"log/{conv_id}.txt"
        try:
            with open(file_path, 'r', encoding="utf-8-sig") as f:
                for line in f:
                    entry = json.loads(line.strip())
                    if 'roles' not in entry:
                        entry['roles'] = {'user': 'user', 'assistant': 'assistant'}
                    history.append(entry)
        except Exception as e:
            QMessageBox.warning(self, "載入錯誤", f"無法載入對話紀錄: {str(e)}")
        return history
        
    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        layout = QVBoxLayout()
        
        history_limit_spin = QSpinBox()
        history_limit_spin.setRange(1, 20)
        history_limit_spin.setValue(self.history_limit)
        history_limit_spin.valueChanged.connect(lambda v: setattr(self, 'history_limit', v))
        
        layout.addWidget(QLabel("最大歷史紀錄輪數:"))
        layout.addWidget(history_limit_spin)
        
        layout.addWidget(QLabel("使用模型:"))

        # 新增水平布局放置 RadioButton
        model_layout = QHBoxLayout()
        self.v3_radio = QRadioButton("V3")
        self.r1_radio = QRadioButton("R1")
        
        # 设置互斥组
        radio_group = QButtonGroup(dialog)
        radio_group.addButton(self.v3_radio)
        radio_group.addButton(self.r1_radio)
        
        # 设置默认选中
        if self.current_model == "v3":
            self.v3_radio.setChecked(True)
        else:
            self.r1_radio.setChecked(True)
        
        # 连接信号
        self.v3_radio.toggled.connect(lambda: setattr(self, 'current_model', 'v3'))
        self.r1_radio.toggled.connect(lambda: setattr(self, 'current_model', 'r1'))
        model_layout.addWidget(self.v3_radio)
        model_layout.addWidget(self.r1_radio)
        layout.addLayout(model_layout)
        
        # 新增 Use Timestamp 的 Checkbox
        timestamp_checkbox = QCheckBox("Use Timestamp")
        timestamp_checkbox.setChecked(self.use_timestamp)
        timestamp_checkbox.stateChanged.connect(lambda state: setattr(self, 'use_timestamp', state == Qt.Checked))
        layout.addWidget(timestamp_checkbox)
        
        save_btn = QPushButton("保存設置")
        save_btn.clicked.connect(dialog.accept)
        layout.addWidget(save_btn)
        
        dialog.setLayout(layout)
        dialog.exec_()

    def show_conversation_details(self, item):
        conv_id = item.data(Qt.UserRole)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"對話詳情 - {conv_id}")
        layout = QVBoxLayout()
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        
        history = self.conversations[conv_id]['history']
        for entry in history:
            text_edit.append(f"[用户 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry['timestamp']))}]")
            text_edit.append(entry['prompt'])
            text_edit.append("")
            text_edit.append(f"[助理 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry['timestamp']))}]")
            text_edit.append(entry['response'])
            text_edit.append("\n" + "-"*50 + "\n")
        
        layout.addWidget(text_edit)
        dialog.setLayout(layout)
        dialog.resize(800, 600)
        dialog.exec_()

    def get_stylesheet(self):
        return """
            QMainWindow {
                background-color: #f0f0f0;
            }
            QGroupBox {
                border: 1px solid gray;
                border-radius: 5px;
                margin-top: 1ex;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
            QTextEdit {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #ddd;
            }
            QListWidget::item:hover {
                background-color: #e0e0e0;
            }
        """
    def resizeEvent(self, event):
        super().resizeEvent(event)
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            self.adjust_item_height(item)

if __name__ == '__main__':
    app = QApplication([])
    window = DeepSeekUI()
    window.show()
    app.exec_()