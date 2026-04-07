// Utility for configuring marked.js with Math support via KaTeX
function setupMarkdownCompiler() {
    if (!window.marked || !window.renderMathInElement) return;
    
    // We'll let DOMPurify handle HTML sanitization
    // We use a custom marked renderer to handle math blocks before KaTeX processes the DOM
    const renderer = new marked.Renderer();
    
    marked.setOptions({
        renderer: renderer,
        gfm: true,
        breaks: true
    });
}

function processContent(text) {
    if (!window.marked || !window.DOMPurify) return text;
    
    // Convert Markdown
    let html = marked.parse(text);
    
    // Sanitize
    html = DOMPurify.sanitize(html, {
        ADD_TAGS: ['math', 'mrow', 'mi', 'mn', 'mo', 'ms', 'mspace', 'mtext', 'menclose', 'merror', 'mfrac', 'mpadded', 'mphantom', 'mroot', 'mrow', 'msqrt', 'mstyle', 'mmultiscripts', 'mover', 'mprescripts', 'msub', 'msubsup', 'msup', 'munder', 'munderover', 'none', 'semantics', 'annotation', 'annotation-xml'],
        ADD_ATTR: ['mathvariant', 'mathsize', 'mathcolor', 'mathbackground', 'dir', 'display', 'op', 'center', 'align', 'rowalign', 'columnalign', 'groupalign', 'alignmentscope', 'columnwidth', 'width', 'depth', 'lspace', 'rspace', 'stretchy', 'symmetric', 'maxsize', 'minsize', 'largeop', 'movablelimits', 'accent', 'form', 'separator', 'fence', 'lquote', 'rquote', 'linebreak', 'style', 'href', 'class', 'id']
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

document.addEventListener('DOMContentLoaded', () => {
    setupMarkdownCompiler();
    
    // ---- Theme Toggle ----
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const html = document.documentElement;
            const current = html.getAttribute('data-theme');
            const next = current === 'light' ? 'dark' : 'light';
            html.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        });
    }
    
    // ---- Page: Create Secret ----
    const createBtn = document.getElementById('btn-create');
    if (createBtn) {
        const togglePreviewBtn = document.getElementById('toggle-preview');
        const contentInput = document.getElementById('secret-content');
        const previewContainer = document.getElementById('preview-container');
        
        // Preview toggle
        if (togglePreviewBtn && contentInput && previewContainer) {
            togglePreviewBtn.addEventListener('click', () => {
                const isHidden = previewContainer.classList.contains('preview-hidden');
                if (isHidden) {
                    const text = contentInput.value;
                    if (text.trim()) {
                        previewContainer.innerHTML = processContent(text);
                        renderMath(previewContainer);
                    } else {
                        previewContainer.innerHTML = '<p class="text-secondary italic">Nothing to preview</p>';
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
        
        // Create Request
        createBtn.addEventListener('click', async () => {
            const content = document.getElementById('secret-content').value;
            const password = document.getElementById('privacy-password').value;
            const expiresIn = parseInt(document.getElementById('expiration-time').value);
            const errorMsg = document.getElementById('error-message');
            
            if (!content.trim()) {
                errorMsg.textContent = 'Please enter a secret message.';
                errorMsg.classList.remove('hidden');
                return;
            }
            
            errorMsg.classList.add('hidden');
            
            // Switch button state
            const originalText = createBtn.innerHTML;
            createBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;margin:0"></div>';
            createBtn.disabled = true;
            
            try {
                const res = await fetch('/api/message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: content,
                        password: password || null,
                        expires_in: expiresIn
                    })
                });
                
                const data = await res.json();
                
                if (!res.ok) {
                    throw new Error(data.error || 'Failed to create secret');
                }
                
                // Show success UI
                document.getElementById('create-panel').classList.add('hidden');
                document.getElementById('success-panel').classList.remove('hidden');
                
                // Construct URL with hash
                const baseUrl = window.location.origin;
                const shareUrl = `${baseUrl}/v/${data.id}#${data.key}`;
                document.getElementById('share-url').value = shareUrl;
                
            } catch (err) {
                errorMsg.textContent = err.message;
                errorMsg.classList.remove('hidden');
            } finally {
                createBtn.innerHTML = originalText;
                createBtn.disabled = false;
            }
        });
        
        // Copy to clipboard
        const copyBtn = document.getElementById('btn-copy');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                const urlInput = document.getElementById('share-url');
                urlInput.select();
                urlInput.setSelectionRange(0, 99999);
                navigator.clipboard.writeText(urlInput.value).then(() => {
                    const toast = document.getElementById('copy-toast');
                    toast.classList.remove('hidden');
                    setTimeout(() => {
                        toast.classList.add('hidden');
                    }, 2000);
                });
            });
        }
    }
    
    // ---- Page: View Confirm ----
    const envWrapper = document.getElementById('envelope-wrapper');
    if (envWrapper) {
        envWrapper.addEventListener('click', function(e) {
            // Don't toggle if clicking inside the letter content
            if (e.target.closest('#secret-letter')) return;
            this.classList.add('open');
        });
    }

    const viewBtn = document.getElementById('btn-view');
    if (viewBtn) {
        // Format timestamps
        document.querySelectorAll('[data-time]').forEach(el => {
            const ts = parseInt(el.getAttribute('data-time')) * 1000;
            el.textContent = new Date(ts).toLocaleString();
        });
        
        viewBtn.addEventListener('click', () => {
            const isProtected = viewBtn.getAttribute('data-has-password') === 'true';
            const passwordInput = document.getElementById('view-password');
            const errorMsg = document.getElementById('view-error');
            const id = viewBtn.getAttribute('data-id');
            const hashKeys = window.location.hash.substring(1); // remove '#'
            
            if (!hashKeys) {
                errorMsg.textContent = 'Decryption key missing from URL! Cannot decode message.';
                errorMsg.classList.remove('hidden');
                return;
            }
            
            let password = null;
            if (isProtected) {
                if (!passwordInput.value) {
                    errorMsg.textContent = 'This secret requires a password.';
                    errorMsg.classList.remove('hidden');
                    return;
                }
                password = passwordInput.value;
            }
            
            // Redirect to actual viewing (since it involves POST to decrypt, we can do it via JS and replace HTML)
            // Or store in sessionStorage temporarily and go to /v/view
            // Best approach: Fetch API -> Replace Panel HTML manually
            
            errorMsg.classList.add('hidden');
            const originalText = viewBtn.innerHTML;
            viewBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;margin:0"></div>';
            viewBtn.disabled = true;
            
            fetch(`/api/message/${id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    key: hashKeys,
                    password: password
                })
            })
            .then(res => res.json().then(data => ({status: res.status, body: data})))
            .then(({status, body}) => {
                if (status >= 400) {
                    throw new Error(body.error || 'Failed to decrypt');
                }
                
                // Hide current panel, dynamically show decrypted content.
                // We use DOM manipulation here to prevent URL change
                const panel = document.getElementById('confirm-panel');
                
                // Keep the HTML inside to look like the view page
                panel.innerHTML = `
                    <div class="panel-header protected-header text-left">
                        <h2>Secure Message</h2>
                        <span class="badge badge-danger">Destroyed on Server</span>
                    </div>
                    
                    <div class="secret-content-box markdown-body text-left" id="decrypted-content">
                    </div>
                    
                    <div class="action-row text-center mt-6">
                        <p class="help-text mb-4">This message is no longer available on the server. Do not refresh this page.</p>
                        <a href="/" class="btn btn-secondary">Create your own secret</a>
                    </div>
                `;
                
                const contentBox = document.getElementById('decrypted-content');
                contentBox.innerHTML = processContent(body.content);
                renderMath(contentBox);
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
