// 文件选择器前端逻辑
class FileSelectorUI {
    constructor() {
        this.backend = null;
        this.currentFiles = [];
        this.selectedFiles = new Set();
        
        // 初始化WebChannel通信
        this.initWebChannel();
    }
    
    initUI() {
        // 初始化UI元素，但不绑定事件监听器（事件监听器在initBackend中绑定）
        // 这样可以确保backend已初始化
    }
    
    initWebChannel() {
        // 初始化WebChannel，连接到Python后端
        console.log('开始初始化WebChannel...');
        try {
            if (typeof qt === 'undefined' || typeof qt.webChannelTransport === 'undefined') {
                console.error('WebChannel传输对象不可用');
                return;
            }
            
            new QWebChannel(qt.webChannelTransport, (channel) => {
                console.log('WebChannel连接成功');
                console.log('可用对象:', Object.keys(channel.objects));
                
                // 动态查找后端对象，支持多实例
                let backend_found = false;
                
                // 遍历所有可用对象，找到后端对象
                for (const key in channel.objects) {
                    if (key.startsWith('backend_') || key === 'backend') {
                        this.backend = channel.objects[key];
                        backend_found = true;
                        console.log(`找到后端对象: ${key}`);
                        break;
                    }
                }
                
                if (!backend_found) {
                    // 如果没有找到以backend_开头的对象，尝试使用第一个可用对象
                    const keys = Object.keys(channel.objects);
                    if (keys.length > 0) {
                        this.backend = channel.objects[keys[0]];
                        console.log(`使用第一个可用对象: ${keys[0]}`);
                        backend_found = true;
                    }
                }
                
                if (this.backend) {
                    console.log('后端对象获取成功');
                    console.log('后端方法:', Object.getOwnPropertyNames(Object.getPrototypeOf(this.backend)));
                    this.initBackend();
                } else {
                    console.error('后端对象获取失败');
                }
            });
        } catch (error) {
            console.error('WebChannel初始化失败:', error);
        }
    }
    
    initBackend() {
        // 设置后端信号监听器
        this.backend.filesUpdated.connect((files) => {
            this.currentFiles = files;
            this.renderFiles(files);
        });
        
        this.backend.pathUpdated.connect((path) => {
            this.updatePathInput(path);
        });
        
        this.backend.historyStatusUpdated.connect((canGoBack, canGoForward) => {
            this.updateNavigationButtons(canGoBack, canGoForward);
        });
        
        // 绑定事件监听器 - 现在backend已经初始化完成
        this.bindEvents();
        
        // 初始化数据 - 使用try-catch确保在后端方法不可用时不会崩溃
        try {
            this.loadDrives();
            this.loadCurrentPath();
            this.refreshFiles();
        } catch (error) {
            console.error('初始化后端数据失败:', error);
        }
    }
    
    bindEvents() {
        console.log('绑定事件监听器...');
        
        // 地址栏事件
        const driveSelect = document.getElementById('driveSelect');
        if (driveSelect) {
            driveSelect.addEventListener('change', (e) => {
                console.log('盘符选择改变:', e.target.value);
                try {
                    this.backend.setCurrentPath(e.target.value);
                } catch (error) {
                    console.error('调用setCurrentPath失败:', error);
                }
            });
        }
        
        const goButton = document.getElementById('goButton');
        if (goButton) {
            goButton.addEventListener('click', () => {
                const path = document.getElementById('pathInput').value;
                console.log('点击前往按钮，路径:', path);
                try {
                    this.backend.setCurrentPath(path);
                } catch (error) {
                    console.error('调用setCurrentPath失败:', error);
                }
            });
        }
        
        const pathInput = document.getElementById('pathInput');
        if (pathInput) {
            pathInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const path = e.target.value;
                    console.log('路径输入框回车，路径:', path);
                    try {
                        this.backend.setCurrentPath(path);
                    } catch (error) {
                        console.error('调用setCurrentPath失败:', error);
                    }
                }
            });
        }
        
        // 导航按钮事件
        const backButton = document.getElementById('backButton');
        if (backButton) {
            backButton.addEventListener('click', () => {
                console.log('点击后退按钮');
                try {
                    this.backend.goBack();
                } catch (error) {
                    console.error('调用goBack失败:', error);
                }
            });
        }
        
        const forwardButton = document.getElementById('forwardButton');
        if (forwardButton) {
            forwardButton.addEventListener('click', () => {
                console.log('点击前进按钮');
                try {
                    this.backend.goForward();
                } catch (error) {
                    console.error('调用goForward失败:', error);
                }
            });
        }
        
        const refreshButton = document.getElementById('refreshButton');
        if (refreshButton) {
            refreshButton.addEventListener('click', () => {
                console.log('点击刷新按钮');
                this.refreshFiles();
            });
        }
        
        // 筛选和排序事件
        const filterButton = document.getElementById('filterButton');
        if (filterButton) {
            filterButton.addEventListener('click', () => {
                const pattern = document.getElementById('filterInput').value;
                console.log('点击筛选按钮，模式:', pattern);
                try {
                    this.backend.setFilter(pattern);
                } catch (error) {
                    console.error('调用setFilter失败:', error);
                }
            });
        }
        
        const sortButton = document.getElementById('sortButton');
        if (sortButton) {
            sortButton.addEventListener('click', () => {
                const sortBy = document.getElementById('sortBySelect').value;
                const sortOrder = document.getElementById('sortOrderSelect').value;
                console.log('点击排序按钮，方式:', sortBy, '顺序:', sortOrder);
                try {
                    this.backend.setSortBy(sortBy);
                    this.backend.setSortOrder(sortOrder);
                } catch (error) {
                    console.error('调用排序方法失败:', error);
                }
            });
        }
        
        // 选择按钮事件
        const selectAllButton = document.getElementById('selectAllButton');
        if (selectAllButton) {
            selectAllButton.addEventListener('click', () => {
                console.log('点击全选按钮');
                try {
                    this.backend.selectAll();
                    // 从后端获取最新的选择状态
                    this.backend.getSelectedFiles((selectedFiles) => {
                        console.log('全选后获取到的文件:', selectedFiles);
                        if (Array.isArray(selectedFiles)) {
                            this.selectedFiles = new Set(selectedFiles);
                            this.refreshSelection();
                        }
                    });
                } catch (error) {
                    console.error('全选失败:', error);
                }
            });
        }
        
        const selectAllFilesButton = document.getElementById('selectAllFilesButton');
        if (selectAllFilesButton) {
            selectAllFilesButton.addEventListener('click', () => {
                console.log('点击仅全选文件按钮');
                try {
                    this.backend.selectAllFiles();
                    // 从后端获取最新的选择状态
                    this.backend.getSelectedFiles((selectedFiles) => {
                        console.log('仅全选文件后获取到的文件:', selectedFiles);
                        if (Array.isArray(selectedFiles)) {
                            this.selectedFiles = new Set(selectedFiles);
                            this.refreshSelection();
                        }
                    });
                } catch (error) {
                    console.error('仅全选文件失败:', error);
                }
            });
        }
        
        const selectNoneButton = document.getElementById('selectNoneButton');
        if (selectNoneButton) {
            selectNoneButton.addEventListener('click', () => {
                console.log('点击取消全选按钮');
                try {
                    this.backend.selectNone();
                    this.selectedFiles.clear();
                    this.refreshSelection();
                } catch (error) {
                    console.error('取消全选失败:', error);
                }
            });
        }
        
        const invertSelectionButton = document.getElementById('invertSelectionButton');
        if (invertSelectionButton) {
            invertSelectionButton.addEventListener('click', () => {
                console.log('点击反选按钮');
                try {
                    this.backend.invertSelection();
                    // 从后端获取最新的选择状态
                    this.backend.getSelectedFiles((selectedFiles) => {
                        console.log('反选后获取到的文件:', selectedFiles);
                        if (Array.isArray(selectedFiles)) {
                            this.selectedFiles = new Set(selectedFiles);
                            this.refreshSelection();
                        }
                    });
                } catch (error) {
                    console.error('反选失败:', error);
                }
            });
        }
        
        // 输出按钮事件
        const outputButton = document.getElementById('outputButton');
        if (outputButton) {
            outputButton.addEventListener('click', () => {
                console.log('点击输出按钮');
                this.outputSelectedFiles();
            });
        }
    }
    
    loadDrives() {
        // 加载系统盘符
        try {
            this.backend.getDrives((drives) => {
                console.log('获取到盘符列表:', drives);
                const driveSelect = document.getElementById('driveSelect');
                
                driveSelect.innerHTML = '';
                if (Array.isArray(drives)) {
                    drives.forEach(drive => {
                        const option = document.createElement('option');
                        option.value = drive;
                        option.textContent = drive;
                        driveSelect.appendChild(option);
                    });
                } else {
                    console.error('获取到的盘符不是数组:', drives);
                }
            });
        } catch (error) {
            console.error('加载盘符失败:', error);
        }
    }
    
    loadCurrentPath() {
        // 加载当前路径
        try {
            this.backend.getCurrentPath((path) => {
                console.log('获取到当前路径:', path);
                if (typeof path === 'string') {
                    this.updatePathInput(path);
                    
                    // 更新盘符选择
                    const driveSelect = document.getElementById('driveSelect');
                    const drive = path.split(':')[0] + ':/';
                    driveSelect.value = drive;
                } else {
                    console.error('获取到的路径不是字符串:', path);
                }
            });
        } catch (error) {
            console.error('加载当前路径失败:', error);
        }
    }
    
    updatePathInput(path) {
        // 更新路径输入框
        document.getElementById('pathInput').value = path;
    }
    
    updateNavigationButtons(canGoBack, canGoForward) {
        // 更新导航按钮状态
        document.getElementById('backButton').disabled = !canGoBack;
        document.getElementById('forwardButton').disabled = !canGoForward;
    }
    
    refreshFiles() {
        // 刷新文件列表
        this.backend.refreshFiles();
    }
    
    renderFiles(files) {
        // 渲染文件列表
        const filesList = document.getElementById('filesList');
        filesList.innerHTML = '';
        
        files.forEach(file => {
            const fileCard = this.createFileCard(file);
            filesList.appendChild(fileCard);
        });
        
        // 刷新选择状态
        this.refreshSelection();
    }
    
    createFileCard(file) {
        // 创建文件卡片
        const card = document.createElement('div');
        card.className = 'file-card';
        card.dataset.path = file.path;
        
        // 缩略图
        const thumbnail = document.createElement('div');
        thumbnail.className = `file-thumbnail ${file.thumbnail}`;
        
        // 如果是实际图片文件，显示图片
        if (file.thumbnail.startsWith('C:') || file.thumbnail.startsWith('/')) {
            const img = document.createElement('img');
            img.src = file.thumbnail;
            img.alt = file.name;
            thumbnail.appendChild(img);
        }
        
        // 文件名
        const name = document.createElement('div');
        name.className = 'file-name';
        name.textContent = file.name;
        
        // 文件信息
        const info = document.createElement('div');
        info.className = 'file-info';
        
        // 文件大小
        const size = document.createElement('div');
        size.className = 'file-size';
        size.textContent = file.is_dir ? '目录' : this.formatFileSize(file.size);
        
        // 文件修改时间
        const date = document.createElement('div');
        date.className = 'file-date';
        date.textContent = this.formatDate(file.modify_time);
        
        info.appendChild(size);
        info.appendChild(date);
        
        // 复选框
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'file-checkbox';
        checkbox.checked = this.selectedFiles.has(file.path);
        
        // 绑定事件
        checkbox.addEventListener('change', (e) => {
            this.toggleFileSelection(file.path, e.target.checked);
        });
        
        card.addEventListener('click', (e) => {
            // 如果点击的是复选框，不触发卡片点击
            if (e.target === checkbox) {
                return;
            }
            
            if (file.is_dir) {
                // 目录点击，进入目录
                this.backend.setCurrentPath(file.path);
            } else {
                // 文件点击，切换选择状态
                const isSelected = this.selectedFiles.has(file.path);
                this.toggleFileSelection(file.path, !isSelected);
            }
        });
        
        // 组装卡片
        card.appendChild(checkbox);
        card.appendChild(thumbnail);
        card.appendChild(name);
        card.appendChild(info);
        
        return card;
    }
    
    toggleFileSelection(filePath, isSelected) {
        // 切换文件选择状态
        if (isSelected) {
            this.selectedFiles.add(filePath);
        } else {
            this.selectedFiles.delete(filePath);
        }
        
        // 更新后端状态
        this.backend.toggleSelectFile(filePath, isSelected);
        
        // 更新UI
        this.refreshSelection();
    }
    
    refreshSelection() {
        // 刷新选择状态
        const cards = document.querySelectorAll('.file-card');
        
        cards.forEach(card => {
            const path = card.dataset.path;
            const isSelected = this.selectedFiles.has(path);
            
            if (isSelected) {
                card.classList.add('selected');
            } else {
                card.classList.remove('selected');
            }
            
            // 更新复选框状态
            const checkbox = card.querySelector('.file-checkbox');
            if (checkbox) {
                checkbox.checked = isSelected;
            }
        });
        
        // 更新选中计数
        this.updateSelectedCount();
    }
    
    updateSelectedCount() {
        // 更新选中文件计数
        const count = this.selectedFiles.size;
        document.getElementById('selectedCount').textContent = `已选择 ${count} 个文件`;
    }
    
    outputSelectedFiles() {
        // 输出选中的文件
        try {
            this.backend.getSelectedFiles((selectedFiles) => {
                console.log('输出选中文件:', selectedFiles);
                if (Array.isArray(selectedFiles)) {
                    // 显示选中的文件路径
                    alert('选中的文件路径：\n' + selectedFiles.join('\n'));
                    
                    // 清空选择状态
                    this.backend.clearSelection();
                    this.selectedFiles.clear();
                    this.refreshSelection();
                    
                    // 可以根据需要扩展，比如复制到剪贴板
                    // navigator.clipboard.writeText(selectedFiles.join('\n'));
                }
            });
        } catch (error) {
            console.error('输出选中文件失败:', error);
        }
    }
    
    formatFileSize(size) {
        // 格式化文件大小
        if (size === 0) return '0 B';
        
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(size) / Math.log(k));
        
        return parseFloat((size / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    formatDate(timestamp) {
        // 格式化日期
        const date = new Date(timestamp * 1000);
        return date.toLocaleString();
    }
}

// 页面加载完成后初始化
window.addEventListener('DOMContentLoaded', () => {
    new FileSelectorUI();
});
