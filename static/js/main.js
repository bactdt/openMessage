function setupMarkdownCompiler() {
    if (!window.marked || !window.renderMathInElement) return;
    marked.setOptions({
        gfm: true,
        breaks: true
    });
}

function isV2E2EEnabled() {
    var meta = document.querySelector('meta[name="openmessage-v2-e2e"]');
    return !!(meta && meta.getAttribute('content') === 'enabled' && window.crypto && window.crypto.subtle);
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

async function createV2Message(payload) {
    var res = await fetch('/api/v2/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    var body = await res.json();
    return { status: res.status, body: body };
}

async function readV2Message(id, payload) {
    var res = await fetch('/api/v2/message/' + id, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    var body = await res.json();
    return { status: res.status, body: body };
}

async function readV2MessageWithRetry(id, payload) {
    var result = await readV2Message(id, payload);
    if (result.status === 409 && result.body && result.body.retryable) {
        await delay(150);
        result = await readV2Message(id, payload);
    }
    return result;
}

function bytesToBase64Url(bytes) {
    var binary = '';
    bytes.forEach(function(byte) {
        binary += String.fromCharCode(byte);
    });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function base64UrlToBytes(value) {
    var base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    base64 += '='.repeat((4 - base64.length % 4) % 4);
    var binary = atob(base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
}

async function encryptV2Content(content) {
    var key = await window.crypto.subtle.generateKey(
        { name: 'AES-GCM', length: 256 },
        true,
        ['encrypt', 'decrypt']
    );
    var rawKey = await window.crypto.subtle.exportKey('raw', key);
    var iv = window.crypto.getRandomValues(new Uint8Array(12));
    var encoded = new TextEncoder().encode(content);
    var encrypted = await window.crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv }, key, encoded);

    return {
        fragment: 'v2.' + bytesToBase64Url(new Uint8Array(rawKey)),
        payload: {
            version: 'v2',
            alg: 'AES-GCM',
            iv: bytesToBase64Url(iv),
            ciphertext: bytesToBase64Url(new Uint8Array(encrypted))
        }
    };
}

async function decryptV2Content(payload, fragment) {
    if (!fragment || fragment.indexOf('v2.') !== 0) {
        throw new Error('v2 decryption key missing from URL.');
    }
    if (!payload || payload.version !== 'v2' || payload.alg !== 'AES-GCM') {
        throw new Error('Invalid v2 payload.');
    }

    var keyBytes = base64UrlToBytes(fragment.substring(3));
    var key = await window.crypto.subtle.importKey(
        'raw',
        keyBytes,
        { name: 'AES-GCM' },
        false,
        ['decrypt']
    );
    var iv = base64UrlToBytes(payload.iv);
    var ciphertext = base64UrlToBytes(payload.ciphertext);
    var decrypted = await window.crypto.subtle.decrypt({ name: 'AES-GCM', iv: iv }, key, ciphertext);
    return new TextDecoder().decode(decrypted);
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
                var data;
                var fragment;

                if (isV2E2EEnabled()) {
                    var encrypted = await encryptV2Content(content);
                    var v2Result = await createV2Message({
                        payload: encrypted.payload,
                        password: password || null,
                        expires_in: expiresIn
                    });
                    data = v2Result.body;
                    if (v2Result.status >= 400) {
                        throw new Error(data.error || 'Failed to create secret');
                    }
                    fragment = encrypted.fragment;
                } else {
                    var res = await fetch('/api/message', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            content: content,
                            password: password || null,
                            expires_in: expiresIn
                        })
                    });

                    data = await res.json();

                    if (!res.ok) {
                        throw new Error(data.error || 'Failed to create secret');
                    }
                    fragment = data.key;
                }

                document.getElementById('create-panel').classList.add('hidden');
                document.getElementById('success-panel').classList.remove('hidden');

                var baseUrl = window.location.origin;
                var shareUrl = baseUrl + '/v/' + data.id + '#' + fragment;
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

            var readPromise;
            if (hashKeys.indexOf('v2.') === 0 && isV2E2EEnabled()) {
                readPromise = readV2MessageWithRetry(id, { password: password })
                    .then(async function(result) {
                        if (result.status >= 400) {
                            throw new Error(result.body.error || 'Failed to decrypt');
                        }
                        return {
                            status: result.status,
                            body: { content: await decryptV2Content(result.body.payload, hashKeys) }
                        };
                    });
            } else {
                readPromise = readMessageWithRetry(id, {
                    key: hashKeys,
                    password: password
                });
            }

            readPromise
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
