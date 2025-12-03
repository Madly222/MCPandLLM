document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('prompt');
    const sendBtn = document.getElementById('sendBtn');
    const chatContainer = document.getElementById('chat-container');
    const uploadBtn = document.getElementById('uploadBtn');
    const fileInput = document.getElementById('fileInput');
    const downloadBtn = document.getElementById('downloadBtn');

    let currentDownloadFile = null;
    let downloadCheckInterval = null;

    if (!input || !sendBtn || !chatContainer) {
        console.log('Элементы чата не найдены (возможно страница логина)');
        return;
    }

    sendBtn.addEventListener('click', sendPrompt);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendPrompt();
    });

    async function sendPrompt() {
        const message = input.value.trim();
        if (!message) return;

        appendChat('Вы', message);
        input.value = '';

        try {
            const res = await fetch('/query', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({ prompt: message })
            });

            const data = await res.json();
            const response = data.response || 'Ошибка при получении ответа';
            appendChat('Помощник', response);

            checkForDownloadLink(response);
        } catch (err) {
            appendChat('Система', 'Ошибка при соединении с сервером');
            console.error(err);
        }
    }

    function checkForDownloadLink(text) {
        const patterns = [
            /\/download\/([^\s"'<>]+\.xlsx?)/gi,
            /Скачать:\s*\S*\/download\/([^\s"'<>]+\.xlsx?)/gi,
            /download_url['":\s]+[^\s]*\/download\/([^\s"'<>]+\.xlsx?)/gi
        ];

        for (const pattern of patterns) {
            const matches = text.matchAll(pattern);
            for (const match of matches) {
                if (match[1]) {
                    setDownloadFile(match[1]);
                    return;
                }
            }
        }
    }

    function setDownloadFile(filename) {
        currentDownloadFile = filename;
        updateDownloadButton(true);
        startDownloadCheck();
    }

    function updateDownloadButton(active) {
        if (!downloadBtn) return;

        if (active) {
            downloadBtn.classList.add('active');
            downloadBtn.disabled = false;
            downloadBtn.title = `Скачать: ${currentDownloadFile}`;
        } else {
            downloadBtn.classList.remove('active');
            downloadBtn.disabled = true;
            downloadBtn.title = 'Нет файла для скачивания';
            currentDownloadFile = null;
        }
    }

    function startDownloadCheck() {
        if (downloadCheckInterval) {
            clearInterval(downloadCheckInterval);
        }

        downloadCheckInterval = setInterval(async () => {
            if (!currentDownloadFile) {
                clearInterval(downloadCheckInterval);
                return;
            }

            try {
                const res = await fetch(`/downloads/check/${encodeURIComponent(currentDownloadFile)}`, {
                    credentials: 'include'
                });
                const data = await res.json();

                if (!data.exists) {
                    updateDownloadButton(false);
                    clearInterval(downloadCheckInterval);
                }
            } catch (err) {
                console.error('Ошибка проверки файла:', err);
            }
        }, 30000);
    }

    if (downloadBtn) {
        downloadBtn.addEventListener('click', async () => {
            if (!currentDownloadFile || downloadBtn.disabled) return;

            try {
                const res = await fetch(`/downloads/check/${encodeURIComponent(currentDownloadFile)}`, {
                    credentials: 'include'
                });
                const data = await res.json();

                if (data.exists) {
                    window.location.href = `/download/${encodeURIComponent(currentDownloadFile)}`;
                } else {
                    updateDownloadButton(false);
                    alert('Файл больше не доступен');
                }
            } catch (err) {
                console.error('Ошибка скачивания:', err);
                alert('Ошибка при скачивании файла');
            }
        });
    }

    checkAvailableDownloads();

    async function checkAvailableDownloads() {
        try {
            const res = await fetch('/downloads/available', {
                credentials: 'include'
            });
            const data = await res.json();

            if (data.files && data.files.length > 0) {
                const latestFile = data.files[0];
                setDownloadFile(latestFile.filename);
            }
        } catch (err) {
            console.error('Ошибка получения списка файлов:', err);
        }
    }

    function appendChat(role, text) {
        const msgDiv = document.createElement('div');
        if (role === 'Вы') msgDiv.className = 'message user-msg';
        else if (role === 'Помощник') msgDiv.className = 'message assistant-msg';
        else msgDiv.className = 'message';

        msgDiv.innerText = `${role}:\n${text}`;
        chatContainer.appendChild(msgDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    if (uploadBtn && fileInput) {
        uploadBtn.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', async () => {
            const file = fileInput.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/upload', {
                    method: 'POST',
                    credentials: 'include',
                    body: formData
                });

                const data = await res.json();
                alert(data.message || 'Файл загружен');
            } catch (err) {
                alert('Ошибка при загрузке файла');
                console.error(err);
            }

            fileInput.value = '';
        });
    }

    // Tooltip первого уровня (над кнопкой ?)
    const tooltip = document.querySelector('.tooltip');
    if (tooltip) {
        const tooltipText = tooltip.querySelector('.tooltiptext');
        let hideTimeout;

        tooltip.addEventListener('mouseenter', () => {
            if (hideTimeout) clearTimeout(hideTimeout);
            tooltipText.style.visibility = 'visible';
            tooltipText.style.opacity = '1';
        });

        tooltip.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                tooltipText.style.visibility = 'hidden';
                tooltipText.style.opacity = '0';
            }, 300);
        });

        tooltipText.addEventListener('mouseenter', () => {
            if (hideTimeout) clearTimeout(hideTimeout);
        });

        tooltipText.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                tooltipText.style.visibility = 'hidden';
                tooltipText.style.opacity = '0';
            }, 200);
        });
    }

    // Inner tooltip (второй уровень) - слева от первого блока (на ПК) или сверху (на мобильных)
    const innerTooltips = document.querySelectorAll('.inner-tooltip');
    const isMobile = () => window.innerWidth <= 480;

    innerTooltips.forEach(inner => {
        const innerText = inner.querySelector('.inner-tooltiptext');
        const closeBtn = inner.querySelector('.close-tooltip');
        if (!innerText) return;

        function showTooltip() {
            if (isMobile()) {
                innerText.classList.add('active');
            } else {
                innerText.style.visibility = 'visible';
                innerText.style.opacity = '1';

                innerText.style.right = '100%';
                innerText.style.left = 'auto';
                innerText.style.top = '50%';
                innerText.style.bottom = 'auto';
                innerText.style.transform = 'translateY(-50%)';
                innerText.style.marginRight = '10px';
                innerText.style.marginLeft = '0';
                innerText.style.marginBottom = '0';

                requestAnimationFrame(() => {
                    const rect = innerText.getBoundingClientRect();
                    const viewportHeight = window.innerHeight;

                    if (rect.left < 5) {
                        innerText.style.right = 'auto';
                        innerText.style.left = '100%';
                        innerText.style.marginRight = '0';
                        innerText.style.marginLeft = '10px';
                    }

                    const newRect = innerText.getBoundingClientRect();

                    if (newRect.top < 5) {
                        innerText.style.top = '0';
                        innerText.style.transform = 'none';
                    }

                    if (newRect.bottom > viewportHeight - 5) {
                        innerText.style.top = 'auto';
                        innerText.style.bottom = '0';
                        innerText.style.transform = 'none';
                    }
                });
            }
        }

        function hideTooltip() {
            if (isMobile()) {
                innerText.classList.remove('active');
            } else {
                innerText.style.visibility = 'hidden';
                innerText.style.opacity = '0';
            }
        }

        function hideAllTooltips() {
            document.querySelectorAll('.inner-tooltiptext').forEach(t => {
                t.classList.remove('active');
                t.style.visibility = 'hidden';
                t.style.opacity = '0';
            });
        }

        inner.addEventListener('mouseenter', () => {
            if (!isMobile()) {
                showTooltip();
            }
        });

        inner.addEventListener('mouseleave', () => {
            if (!isMobile()) {
                hideTooltip();
            }
        });

        inner.addEventListener('click', (e) => {
            if (isMobile()) {
                e.preventDefault();
                e.stopPropagation();

                const isActive = innerText.classList.contains('active');
                hideAllTooltips();

                if (!isActive) {
                    showTooltip();
                }
            }
        });

        if (closeBtn) {
            closeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                hideTooltip();
            });
        }
    });

    document.addEventListener('click', (e) => {
        if (isMobile() && !e.target.closest('.tooltip')) {
            document.querySelectorAll('.inner-tooltiptext').forEach(t => {
                t.classList.remove('active');
            });
        }
    });
});