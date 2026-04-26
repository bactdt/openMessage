function setupMarkdownCompiler() {
    if (!window.marked || !window.renderMathInElement) return;
    marked.setOptions({
        gfm: true,
        breaks: true
    });
}

function processContent(text) {
    if (!window.marked || !window.DOMPurify) return text;
    let html = marked.parse(text);
    html = DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        ADD_TAGS: ['math', 'mrow', 'mi', 'mn', 'mo', 'ms', 'mspace', 'mtext', 'menclose', 'merror', 'mfrac', 'mpadded', 'mphantom', 'mroot', 'mrow', 'msqrt', 'mstyle', 'mmultiscripts', 'mover', 'mprescripts', 'msub', 'msubsup', 'msup', 'munder', 'munderover', 'none', 'semantics', 'annotation', 'annotation-xml'],
        ADD_ATTR: ['mathvariant', 'mathsize', 'mathcolor', 'mathbackground', 'dir', 'display', 'op', 'center', 'align', 'rowalign', 'columnalign', 'groupalign', 'alignmentscope', 'columnwidth', 'width', 'depth', 'lspace', 'rspace', 'stretchy', 'symmetric', 'maxsize', 'minsize', 'largeop', 'movablelimits', 'accent', 'form', 'separator', 'fence', 'lquote', 'rquote', 'linebreak', 'class'],
        FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed'],
        FORBID_ATTR: ['style', 'onerror', 'onclick', 'onload', 'id']
    });
    return html;
}

function renderMath(element) {
    if (window.renderMathInElement) {
        window.renderMathInElement(element, {
            delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false},
                {left: '\\(', right: '\\)', display: false},
                {left: '\\[', right: '\\]', display: true}
            ],
            throwOnError: false
        });
    }
}

function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        return Promise.resolve();
    } catch (e) {
        return Promise.reject(e);
    } finally {
        document.body.removeChild(textarea);
    }
}

function delay(ms) {
    return new Promise(function(resolve) {
        setTimeout(resolve, ms);
    });
}

async function readMessage(id, payload) {
    var res = await fetch('/api/message/' + id, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    var body = await res.json();
    return { status: res.status, body: body };
}

async function readMessageWithRetry(id, payload) {
    var result = await readMessage(id, payload);
    if (result.status === 409 && result.body && result.body.retryable) {
        await delay(150);
        result = await readMessage(id, payload);
    }
    return result;
}

document.addEventListener('DOMContentLoaded', () => {
    setupMarkdownCompiler();

    var themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            var html = document.documentElement;
            var current = html.getAttribute('data-theme');
            var next = current === 'light' ? 'dark' : 'light';
            html.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        });
    }

    var createBtn = document.getElementById('btn-create');
    if (createBtn) {
        var togglePreviewBtn = document.getElementById('toggle-preview');
        var contentInput = document.getElementById('secret-content');
        var previewContainer = document.getElementById('preview-container');

        if (togglePreviewBtn && contentInput && previewContainer) {
            togglePreviewBtn.addEventListener('click', () => {
                var isHidden = previewContainer.classList.contains('preview-hidden');
                if (isHidden) {
                    var text = contentInput.value;
                    if (text.trim()) {
                        previewContainer.innerHTML = processContent(text);
                        renderMath(previewContainer);
                    } else {
                        previewContainer.innerHTML = '<p style="color: var(--color-text-muted); font-style: italic;">Nothing to preview</p>';
                    }
                    contentInput.classList.add('hidden');
                    previewContainer.classList.remove('preview-hidden');
                    togglePreviewBtn.textContent = 'Edit Message';
                } else {
                    contentInput.classList.remove('hidden');
                    previewContainer.classList.add('preview-hidden');
                    togglePreviewBtn.textContent = 'Show Preview';
                }
            });
        }

        createBtn.addEventListener('click', async () => {
            var content = document.getElementById('secret-content').value;
            var password = document.getElementById('privacy-password').value;
            var expiresIn = parseInt(document.getElementById('expiration-time').value);
            var errorMsg = document.getElementById('error-message');

            if (!content.trim()) {
                errorMsg.textContent = 'Please enter a secret message.';
                errorMsg.classList.remove('hidden');
                return;
            }

            errorMsg.classList.add('hidden');

            var originalText = createBtn.innerHTML;
            createBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;margin:0"></div>';
            createBtn.disabled = true;

            try {
                var res = await fetch('/api/message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: content,
                        password: password || null,
                        expires_in: expiresIn
                    })
                });

                var data = await res.json();

                if (!res.ok) {
                    throw new Error(data.error || 'Failed to create secret');
                }

                document.getElementById('create-panel').classList.add('hidden');
                document.getElementById('success-panel').classList.remove('hidden');

                var baseUrl = window.location.origin;
                var shareUrl = baseUrl + '/v/' + data.id + '#' + data.key;
                document.getElementById('share-url').value = shareUrl;

            } catch (err) {
                errorMsg.textContent = err.message;
                errorMsg.classList.remove('hidden');
            } finally {
                createBtn.innerHTML = originalText;
                createBtn.disabled = false;
            }
        });

        var copyBtn = document.getElementById('btn-copy');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                var urlInput = document.getElementById('share-url');
                copyToClipboard(urlInput.value).then(() => {
                    var toast = document.getElementById('copy-toast');
                    toast.classList.remove('hidden');
                    setTimeout(() => {
                        toast.classList.add('hidden');
                    }, 2000);
                });
            });
        }
    }

    var envWrapper = document.getElementById('envelope-wrapper');
    var envelopeOpened = false;

    function openEnvelope() {
        if (envelopeOpened) return;
        envelopeOpened = true;
        envWrapper.classList.add('open');

        setTimeout(function() {
            var isProtected = document.getElementById('view-password') !== null;
            if (!isProtected) {
                var viewBtn = document.getElementById('btn-view');
                if (viewBtn) viewBtn.click();
            } else {
                var pwInput = document.getElementById('view-password');
                if (pwInput) pwInput.focus();
            }
        }, 700);
    }

    if (envWrapper) {
        envWrapper.addEventListener('click', function(e) {
            if (e.target.closest('#secret-letter')) return;
            openEnvelope();
        });

        envWrapper.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openEnvelope();
            }
        });
    }

    var viewBtn = document.getElementById('btn-view');
    if (viewBtn) {
        document.querySelectorAll('[data-time]').forEach(function(el) {
            var ts = parseInt(el.getAttribute('data-time')) * 1000;
            el.textContent = new Date(ts).toLocaleString();
        });

        var pwInput = document.getElementById('view-password');
        if (pwInput) {
            pwInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    viewBtn.click();
                }
            });
        }

        viewBtn.addEventListener('click', () => {
            var isProtected = viewBtn.getAttribute('data-has-password') === 'true';
            var errorMsg = document.getElementById('view-error');
            var id = viewBtn.getAttribute('data-id');
            var hashKeys = window.location.hash.substring(1);

            if (!hashKeys) {
                errorMsg.textContent = 'Decryption key missing from URL! Cannot decode message.';
                errorMsg.classList.remove('hidden');
                return;
            }

            var password = null;
            if (isProtected) {
                if (!pwInput.value) {
                    errorMsg.textContent = 'This secret requires a password.';
                    errorMsg.classList.remove('hidden');
                    return;
                }
                password = pwInput.value;
            }

            errorMsg.classList.add('hidden');
            var originalText = viewBtn.innerHTML;
            viewBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;margin:0"></div>';
            viewBtn.disabled = true;

            readMessageWithRetry(id, {
                key: hashKeys,
                password: password
            })
            .then(({status, body}) => {
                if (status >= 400) {
                    throw new Error(body.error || 'Failed to decrypt');
                }

                var panel = document.getElementById('confirm-panel');

                panel.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                panel.style.opacity = '0';
                panel.style.transform = 'translateY(10px)';

                setTimeout(function() {
                    panel.innerHTML = '<div class="card">' +
                        '<div class="protected-header text-left" style="opacity:0;transform:translateY(10px);transition:opacity 0.4s ease,transform 0.4s ease;">' +
                            '<h2 style="font-size:22px;font-weight:700;letter-spacing:-0.25px;">Secure Message</h2>' +
                            '<span class="badge badge-danger">Destroyed on Server</span>' +
                        '</div>' +
                        '<div class="secret-content-box markdown-body text-left" id="decrypted-content" style="opacity:0;transform:translateY(15px);transition:opacity 0.5s ease 0.15s,transform 0.5s ease 0.15s;">' +
                        '</div>' +
                        '<div class="mt-6" style="text-align:center;opacity:0;transition:opacity 0.4s ease 0.35s;">' +
                            '<p class="help-text mb-4">This message is no longer available on the server. Do not refresh this page.</p>' +
                            '<a href="/" class="btn btn-secondary">Create your own secret</a>' +
                        '</div>' +
                    '</div>';

                    var contentBox = document.getElementById('decrypted-content');
                    contentBox.innerHTML = processContent(body.content);
                    renderMath(contentBox);

                    panel.style.opacity = '1';
                    panel.style.transform = 'translateY(0)';

                    requestAnimationFrame(function() {
                        requestAnimationFrame(function() {
                            panel.querySelectorAll('[style*="opacity:0"]').forEach(function(el) {
                                el.style.opacity = '1';
                                el.style.transform = 'translateY(0)';
                            });
                        });
                    });
                }, 300);
            })
            .catch(err => {
                errorMsg.textContent = err.message;
                errorMsg.classList.remove('hidden');
                viewBtn.innerHTML = originalText;
                viewBtn.disabled = false;
            });
        });
    }
});
