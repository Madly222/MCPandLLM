document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('prompt');
    const sendBtn = document.getElementById('sendBtn');
    const chatContainer = document.getElementById('chat-container');
    const uploadBtn = document.getElementById('uploadBtn');
    const fileInput = document.getElementById('fileInput');
    const downloadBtn = document.getElementById('downloadBtn');
    let lastDownloadLink = '';

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
            appendChat('Помощник', data.response || 'Ошибка при получении ответа');

            const foundLink = findDownloadLink(data.response || '');
            if (foundLink) {
                setDownloadLink(foundLink);
            }
        } catch (err) {
            appendChat('Система', 'Ошибка при соединении с сервером');
            console.error(err);
        }
    }

    function findDownloadLink(text) {
        const urlPattern = /(https?:\/\/[\S]+\/download\/[^\s]+|\/download\/[^\s]+)/i;
        const match = text.match(urlPattern);
        if (!match) return '';

        try {
            return new URL(match[0], window.location.origin).href;
        } catch (e) {
            console.error('Не удалось разобрать ссылку на скачивание', e);
            return '';
        }
    }

    function updateDownloadButtonState(isAvailable) {
        if (!downloadBtn) return;
        downloadBtn.disabled = !isAvailable;
        downloadBtn.classList.toggle('active', isAvailable);
        downloadBtn.title = isAvailable ? 'Скачать файл' : 'Нет файла для скачивания';
    }

    async function checkDownloadAvailability() {
        if (!lastDownloadLink) {
            updateDownloadButtonState(false);
            return;
        }

        try {
            const res = await fetch(lastDownloadLink, { method: 'HEAD', credentials: 'include' });
            const available = res.ok;
            updateDownloadButtonState(available);

            if (!available) {
                lastDownloadLink = '';
            }
        } catch (e) {
            console.error('Не удалось проверить доступность файла', e);
            updateDownloadButtonState(false);
        }
    }

    function setDownloadLink(link) {
        lastDownloadLink = link;
        checkDownloadAvailability();
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

    if (downloadBtn) {
        downloadBtn.addEventListener('click', () => {
            if (!lastDownloadLink || downloadBtn.disabled) return;
            window.open(lastDownloadLink, '_blank');
        });

        setInterval(() => {
            if (lastDownloadLink) {
                checkDownloadAvailability();
            }
        }, 30000);

        updateDownloadButtonState(false);
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
                // На мобильных используем класс
                innerText.classList.add('active');
            } else {
                // На ПК используем inline стили
                innerText.style.visibility = 'visible';
                innerText.style.opacity = '1';

                // Сбрасываем позицию на дефолтную (слева)
                innerText.style.right = '100%';
                innerText.style.left = 'auto';
                innerText.style.top = '50%';
                innerText.style.bottom = 'auto';
                innerText.style.transform = 'translateY(-50%)';
                innerText.style.marginRight = '10px';
                innerText.style.marginLeft = '0';
                innerText.style.marginBottom = '0';

                // Проверяем границы экрана после отрисовки
                requestAnimationFrame(() => {
                    const rect = innerText.getBoundingClientRect();
                    const viewportHeight = window.innerHeight;

                    // Если выходит слева за экран
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

        // ПК - hover
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

        // Мобильные - только тап
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

        // Крестик для закрытия
        if (closeBtn) {
            closeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                hideTooltip();
            });
        }
    });

    // Закрыть tooltip при клике вне
    document.addEventListener('click', (e) => {
        if (isMobile() && !e.target.closest('.tooltip')) {
            document.querySelectorAll('.inner-tooltiptext').forEach(t => {
                t.classList.remove('active');
            });
        }
    });
});