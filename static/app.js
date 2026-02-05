const API_BASE = '';
let currentUser = null;
let authToken = null;
let turnstileSiteKey = null;
let turnstileWidgetIds = {
    login: null,
    register: null
};

// Notification System
let notifications = JSON.parse(localStorage.getItem('notifications') || '[]');
let notificationDropdownOpen = false;

const PRICING_BASE_USD = {
    free: 0,
    pro: 19
};

const PRICING_COUNTRY_CONFIG = {
    US: { country: 'United States', currency: 'USD', rate: 1.0 },
    IN: { country: 'India', currency: 'INR', rate: 83.2 },
    GB: { country: 'United Kingdom', currency: 'GBP', rate: 0.79 },
    CA: { country: 'Canada', currency: 'CAD', rate: 1.35 },
    AU: { country: 'Australia', currency: 'AUD', rate: 1.53 },
    DE: { country: 'Germany', currency: 'EUR', rate: 0.92 },
    AE: { country: 'United Arab Emirates', currency: 'AED', rate: 3.67 },
    SG: { country: 'Singapore', currency: 'SGD', rate: 1.35 },
    JP: { country: 'Japan', currency: 'JPY', rate: 149.0 }
};

// URL Routing System
let isNavigating = false; // Flag to prevent recursive navigation

function updateURL(path, replace = false) {
    if (isNavigating) return; // Prevent recursive calls
    const newURL = window.location.origin + path;
    if (replace) {
        window.history.replaceState({ path }, '', newURL);
    } else {
        window.history.pushState({ path }, '', newURL);
    }
}

function getPathFromURL() {
    return window.location.pathname;
}

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        search: params.get('q') || params.get('search') || '',
        category: params.get('category') || '',
        minPrice: params.get('minPrice') || params.get('min_price') || '',
        maxPrice: params.get('maxPrice') || params.get('max_price') || '',
        itemId: params.get('item') || null
    };
}

function buildSearchURL(search, category, minPrice, maxPrice) {
    const params = new URLSearchParams();
    if (search) params.append('q', search);
    if (category) params.append('category', category);
    if (minPrice) params.append('minPrice', minPrice);
    if (maxPrice) params.append('maxPrice', maxPrice);
    const queryString = params.toString();
    return queryString ? `?${queryString}` : '';
}

function handleRoute(skipURLUpdate = false) {
    isNavigating = true; // Set flag to prevent URL updates during route handling
    const path = getPathFromURL();
    const queryParams = getQueryParams();
    
    // Handle routes
    if (path === '/' || path === '') {
        // Homepage - landing page
        showHomepage(skipURLUpdate);
    } else if (path === '/login') {
        showLogin(skipURLUpdate);
    } else if (path === '/register') {
        showRegister(skipURLUpdate);
    } else if (path === '/verify-email') {
        handleEmailVerification(skipURLUpdate);
    } else if (path === '/verify-university-change') {
        handleUniversityChangeVerification(skipURLUpdate);
    } else if (path === '/forgot-password') {
        showForgotPassword(skipURLUpdate);
    } else if (path === '/reset-password') {
        handleResetPasswordPage(skipURLUpdate);
    } else if (path === '/dashboard') {
        showDashboard(skipURLUpdate);
    } else if (path === '/pricing') {
        showPricing(skipURLUpdate);
    } else if (path === '/privacy') {
        showPrivacy(skipURLUpdate);
    } else if (path === '/terms') {
        showTerms(skipURLUpdate);
    } else if (path === '/contact') {
        showContact(skipURLUpdate);
    } else {
        // Unknown route, redirect to homepage
        if (!skipURLUpdate) {
            updateURL('/', true);
        }
        showHomepage(skipURLUpdate);
    }
    isNavigating = false; // Reset flag
}

// Handle browser back/forward buttons
window.addEventListener('popstate', (e) => {
    handleRoute(true); // Skip URL update when handling back/forward
});

// Initialize Turnstile site key
async function initializeTurnstile() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/turnstile-site-key`);
        if (response.ok) {
            const data = await response.json();
            turnstileSiteKey = data.site_key;
            
            if (!turnstileSiteKey) {
                // Hide widgets if no site key is configured
                const loginWidget = document.getElementById('turnstile-login');
                const registerWidget = document.getElementById('turnstile-register');
                if (loginWidget) loginWidget.style.display = 'none';
                if (registerWidget) registerWidget.style.display = 'none';
                return;
            }
            
            // Set site key attribute - Turnstile will auto-render when script loads
            const loginWidget = document.getElementById('turnstile-login');
            const registerWidget = document.getElementById('turnstile-register');
            if (loginWidget) {
                loginWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
            if (registerWidget) {
                registerWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
        }
    } catch (error) {
        console.error('Error loading Turnstile site key:', error);
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    initializeSearchableDropdowns();
    initializePricingSelector();
    
    // Initialize Turnstile
    await initializeTurnstile();
    
    // Set last updated dates for legal pages
    const today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const privacyLastUpdated = document.getElementById('privacyLastUpdated');
    const termsLastUpdated = document.getElementById('termsLastUpdated');
    if (privacyLastUpdated) privacyLastUpdated.textContent = today;
    if (termsLastUpdated) termsLastUpdated.textContent = today;
    
    // Check authentication first
    await checkAuth();
    loadNotifications();
    updateFloatingChatVisibility();
    
    // Handle initial route (use replaceState for initial load)
    handleRoute(true);
    // Update URL once after initial route is handled
    const path = getPathFromURL();
    updateURL(path || '/', true);
});

function setupEventListeners() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    const registerForm = document.getElementById('registerForm');
    if (registerForm) registerForm.addEventListener('submit', handleRegister);
    const forgotPasswordForm = document.getElementById('forgotPasswordForm');
    if (forgotPasswordForm) forgotPasswordForm.addEventListener('submit', handleForgotPassword);
    const resetPasswordForm = document.getElementById('resetPasswordForm');
    if (resetPasswordForm) resetPasswordForm.addEventListener('submit', handleResetPassword);
    const createItemForm = document.getElementById('createItemForm');
    if (createItemForm) createItemForm.addEventListener('submit', handleCreateItem);
    const profileForm = document.getElementById('profileForm');
    if (profileForm) profileForm.addEventListener('submit', handleUpdateProfile);
    const contactForm = document.getElementById('contactForm');
    if (contactForm) contactForm.addEventListener('submit', handleContactSubmit);
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadItems();
        });
    }
    
    // Image preview for multiple file upload
    const imageFileInput = document.getElementById('itemImageFiles');
    if (imageFileInput) {
        imageFileInput.addEventListener('change', handleMultipleImagePreview);
    }
    
    // Profile picture upload
    const profilePictureInput = document.getElementById('profilePictureInput');
    if (profilePictureInput) {
        profilePictureInput.addEventListener('change', handleProfilePicturePreview);
    }
    
    // Update price label when category changes
    const itemCategorySelect = document.getElementById('itemCategory');
    if (itemCategorySelect) {
        itemCategorySelect.addEventListener('change', updatePriceLabel);
    }
    
    // Update price filter placeholders when category filter changes
    const categoryFilter = document.getElementById('categoryFilter');
    if (categoryFilter) {
        categoryFilter.addEventListener('change', updatePriceFilterPlaceholders);
    }
    
    // Documentation form
    const documentationForm = document.getElementById('documentationForm');
    if (documentationForm) {
        documentationForm.addEventListener('submit', handleDocumentationForm);
        initializeYearDropdown();
        loadDocumentationPreferences();
    }
    
    // Document upload form
    const documentUploadForm = document.getElementById('documentUploadForm');
    if (documentUploadForm) {
        documentUploadForm.addEventListener('submit', handleDocumentUpload);
    }
    
    // University email validation and autofill
    const registerEmailInput = document.getElementById('registerEmail');
    if (registerEmailInput) {
        let emailCheckTimeout;
        registerEmailInput.addEventListener('input', (e) => {
            clearTimeout(emailCheckTimeout);
            const email = e.target.value.trim();
            
            // Only check if email looks valid (contains @)
            if (email && email.includes('@')) {
                emailCheckTimeout = setTimeout(() => {
                    checkUniversityByEmail(email);
                }, 500); // Debounce for 500ms
            } else {
                // Clear university if email is invalid
                document.getElementById('registerUniversity').value = '';
                const messageEl = document.getElementById('emailValidationMessage');
                messageEl.style.display = 'none';
            }
        });
    }
}

function updatePriceLabel() {
    const categorySelect = document.getElementById('itemCategory');
    const priceLabel = document.querySelector('label[for="itemPrice"]');
    const priceInput = document.getElementById('itemPrice');
    
    if (categorySelect && priceLabel && priceInput) {
        if (categorySelect.value === 'sublease') {
            priceLabel.textContent = 'Price ($/month) *';
            priceInput.placeholder = 'e.g., 800';
        } else {
            priceLabel.textContent = 'Price ($) *';
            priceInput.placeholder = '';
        }
    }
}

function updatePriceFilterPlaceholders() {
    const categoryFilter = document.getElementById('categoryFilter');
    const minPriceInput = document.getElementById('minPrice');
    const maxPriceInput = document.getElementById('maxPrice');
    
    if (categoryFilter && minPriceInput && maxPriceInput) {
        if (categoryFilter.value === 'sublease') {
            minPriceInput.placeholder = 'Min $/month';
            maxPriceInput.placeholder = 'Max $/month';
        } else {
            minPriceInput.placeholder = 'Min $';
            maxPriceInput.placeholder = 'Max $';
        }
    }
}

async function checkUniversityByEmail(email) {
    const universityInput = document.getElementById('registerUniversity');
    const messageEl = document.getElementById('emailValidationMessage');
    
    if (!email || !email.includes('@')) {
        universityInput.value = '';
        messageEl.style.display = 'none';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/university-by-email?email=${encodeURIComponent(email)}`);
        const data = await response.json();
        
        if (data.is_valid && data.university_name) {
            // Valid university email - autofill university
            universityInput.value = data.university_name;
            messageEl.textContent = `✓ Valid university email domain: ${data.email_domain}`;
            messageEl.style.color = 'var(--success-color)';
            messageEl.style.display = 'block';
        } else {
            // Invalid university email domain
            universityInput.value = '';
            messageEl.textContent = `✗ This email domain (${data.email_domain}) is not recognized. Please use your university email address.`;
            messageEl.style.color = 'var(--danger-color)';
            messageEl.style.display = 'block';
        }
    } catch (error) {
        console.error('Error checking university:', error);
        universityInput.value = '';
        messageEl.textContent = 'Unable to verify email domain. Please try again.';
        messageEl.style.color = 'var(--text-secondary)';
        messageEl.style.display = 'block';
    }
}

async function checkAuth() {
    const token = localStorage.getItem('authToken');
    if (token) {
        authToken = token;
        try {
            const response = await fetch(`${API_BASE}/api/auth/me`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            if (response.ok) {
                currentUser = await response.json();
                updateUIForAuth();
                return true;
            } else {
                localStorage.removeItem('authToken');
                authToken = null;
                return false;
            }
        } catch (error) {
            console.error('Auth check failed:', error);
            localStorage.removeItem('authToken');
            authToken = null;
            return false;
        }
    }
    return false;
}

function updateUIForAuth() {
    if (currentUser) {
        document.getElementById('loginLink').style.display = 'none';
        document.getElementById('registerLink').style.display = 'none';
        document.getElementById('userMenu').style.display = 'block';
        document.getElementById('notificationContainer').style.display = 'block';
        updateNotificationBadge();
        updateFloatingChatVisibility();
        
        // Update homepage buttons
        const heroSellBtn = document.getElementById('heroSellBtn');
        const heroRegisterBtn = document.getElementById('heroRegisterBtn');
        const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
        if (heroSellBtn) heroSellBtn.style.display = 'inline-block';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';
        
        // Update user info with profile picture if available
        const userInfoEl = document.getElementById('userInfo');
        if (currentUser.profile_picture) {
            userInfoEl.innerHTML = `<img src="${getImageUrl(currentUser.profile_picture)}" alt="${currentUser.username}"> <span>${currentUser.username}</span>`;
        } else {
            userInfoEl.innerHTML = `<div style="width: 2rem; height: 2rem; border-radius: 50%; background: rgba(255,255,255,0.3); display: flex; align-items: center; justify-content: center; font-weight: 600;">${(currentUser.full_name || currentUser.username).charAt(0).toUpperCase()}</div> <span>${currentUser.username}</span>`;
        }
        // Only load profile data if we're on the dashboard section
        const currentSection = sessionStorage.getItem('currentSection');
        if (currentSection === 'dashboard' || currentSection === 'profile') {
            loadProfile();
            loadDashboardStats();
        }
    } else {
        document.getElementById('loginLink').style.display = 'block';
        document.getElementById('registerLink').style.display = 'block';
        document.getElementById('userMenu').style.display = 'none';
        document.getElementById('notificationContainer').style.display = 'none';
        updateFloatingChatVisibility();
        
        // Update homepage buttons
        const heroSellBtn = document.getElementById('heroSellBtn');
        const heroRegisterBtn = document.getElementById('heroRegisterBtn');
        const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
        if (heroSellBtn) heroSellBtn.style.display = 'none';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'inline-block';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'inline-block';
    }
}

function toggleUserMenu() {
    const dropdown = document.getElementById('userMenuDropdown');
    dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
}

// Notification Functions
function addNotification(title, message, type = 'info', data = null) {
    const notification = {
        id: Date.now(),
        title: title,
        message: message,
        type: type, // 'success', 'error', 'warning', 'info'
        data: data,
        timestamp: new Date().toISOString(),
        read: false
    };
    notifications.unshift(notification);
    // Keep only last 50 notifications
    if (notifications.length > 50) {
        notifications = notifications.slice(0, 50);
    }
    saveNotifications();
    updateNotificationBadge();
    renderNotifications();
    return notification;
}

function saveNotifications() {
    localStorage.setItem('notifications', JSON.stringify(notifications));
}

function loadNotifications() {
    notifications = JSON.parse(localStorage.getItem('notifications') || '[]');
    updateNotificationBadge();
    renderNotifications();
}

function updateNotificationBadge() {
    const badge = document.getElementById('notificationBadge');
    const unreadCount = notifications.filter(n => !n.read).length;
    if (badge) {
        if (unreadCount > 0) {
            badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    }
}

function renderNotifications() {
    const list = document.getElementById('notificationList');
    if (!list) return;
    
    if (notifications.length === 0) {
        list.innerHTML = '<p style="text-align: center; padding: 1rem; color: var(--text-secondary);">No notifications</p>';
        return;
    }
    
    list.innerHTML = notifications.map(notif => {
        const date = new Date(notif.timestamp);
        const timeAgo = getTimeAgo(date);
        const icon = getNotificationIcon(notif.type);
        const readClass = notif.read ? 'read' : '';
        
        // Format message with line breaks
        const formattedMessage = escapeHtml(notif.message).replace(/\n/g, '<br>');
        
        return `
            <div class="notification-item ${readClass}" onclick="markNotificationRead(${notif.id})">
                <div class="notification-icon ${notif.type}">${icon}</div>
                <div class="notification-content">
                    <div class="notification-title">${escapeHtml(notif.title)}</div>
                    <div class="notification-message">${formattedMessage}</div>
                    <div class="notification-time">${timeAgo}</div>
                </div>
                ${!notif.read ? '<div class="notification-dot"></div>' : ''}
            </div>
        `;
    }).join('');
}

function getNotificationIcon(type) {
    const icons = {
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️'
    };
    return icons[type] || 'ℹ️';
}

function getTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Convert markdown to HTML for AI responses
function markdownToHtml(text) {
    if (!text) return '';
    
    // Escape HTML first to prevent XSS
    let html = escapeHtml(text);
    
    // Convert **bold** to <strong>
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // Convert *italic* to <em> (but not if it's part of **)
    html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
    
    // Convert `code` to <code>
    html = html.replace(/`([^`]+)`/g, '<code style="background: rgba(139, 92, 246, 0.2); padding: 2px 6px; border-radius: 4px; font-family: monospace;">$1</code>');
    
    // Convert bullet points (lines starting with - or •)
    html = html.replace(/^[\-•]\s+(.+)$/gm, '<li>$1</li>');
    
    // Convert numbered lists (lines starting with 1. 2. etc)
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
    
    // Wrap consecutive <li> elements in <ul>
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => {
        return '<ul style="margin: 8px 0; padding-left: 20px; list-style-type: disc;">' + match + '</ul>';
    });
    
    // Convert line breaks to <br> but not inside lists
    html = html.replace(/\n(?!<)/g, '<br>');
    
    // Clean up extra <br> before/after lists
    html = html.replace(/<br><ul/g, '<ul');
    html = html.replace(/<\/ul><br>/g, '</ul>');
    html = html.replace(/<br><li>/g, '<li>');
    html = html.replace(/<\/li><br>/g, '</li>');
    
    return html;
}

function toggleNotifications() {
    const dropdown = document.getElementById('notificationDropdown');
    notificationDropdownOpen = !notificationDropdownOpen;
    dropdown.style.display = notificationDropdownOpen ? 'block' : 'none';
    if (notificationDropdownOpen) {
        renderNotifications();
    }
}

function markNotificationRead(id) {
    const notif = notifications.find(n => n.id === id);
    if (notif && !notif.read) {
        notif.read = true;
        saveNotifications();
        updateNotificationBadge();
        renderNotifications();
    }
}

function clearAllNotifications() {
    if (confirm('Clear all notifications?')) {
        notifications = [];
        saveNotifications();
        updateNotificationBadge();
        renderNotifications();
    }
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const userMenu = document.getElementById('userMenu');
    const dropdown = document.getElementById('userMenuDropdown');
    if (userMenu && dropdown && !userMenu.contains(e.target)) {
        dropdown.style.display = 'none';
    }
    
    const notificationContainer = document.getElementById('notificationContainer');
    const notificationDropdown = document.getElementById('notificationDropdown');
    if (notificationContainer && notificationDropdown && !notificationContainer.contains(e.target)) {
        notificationDropdown.style.display = 'none';
        notificationDropdownOpen = false;
    }
});

function showMessage(text, type = 'success') {
    const messageEl = document.getElementById('message');
    messageEl.textContent = text;
    messageEl.className = `message ${type} show`;
    setTimeout(() => {
        messageEl.classList.remove('show');
    }, 3000);
}

// Navigation
function showHomepage(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('homepageSection').style.display = 'block';
    // Update button visibility based on auth status
    const heroRegisterBtn = document.getElementById('heroRegisterBtn');
    const heroLoginBtn = document.getElementById('heroLoginBtn');
    const heroDashboardBtn = document.getElementById('heroDashboardBtn');
    const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
    const ctaDashboardBtn = document.getElementById('ctaDashboardBtn');
    
    if (currentUser) {
        // Logged in: show dashboard buttons, hide login/register
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (heroLoginBtn) heroLoginBtn.style.display = 'none';
        if (heroDashboardBtn) heroDashboardBtn.style.display = 'inline-flex';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';
        if (ctaDashboardBtn) ctaDashboardBtn.style.display = 'inline-flex';
    } else {
        // Logged out: show login/register, hide dashboard
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'inline-flex';
        if (heroLoginBtn) heroLoginBtn.style.display = 'inline-flex';
        if (heroDashboardBtn) heroDashboardBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'inline-flex';
        if (ctaDashboardBtn) ctaDashboardBtn.style.display = 'none';
    }
    
    if (!skipURLUpdate) {
        updateURL('/', false); // Use pushState for navigation
    }
}

function showLogin(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('loginSection').style.display = 'block';
    
    // Ensure Turnstile widget is properly initialized
    const loginWidget = document.getElementById('turnstile-login');
    if (loginWidget) {
        if (turnstileSiteKey) {
            // Make sure widget is visible
            loginWidget.style.display = 'block';
            // Set site key if not already set
            if (!loginWidget.getAttribute('data-sitekey')) {
                loginWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
            
            // Wait a bit for Turnstile script to load, then render
            const renderWidget = () => {
                if (window.turnstile) {
                    try {
                        // Check if widget is already rendered by trying to get response
                        const existingToken = window.turnstile.getResponse(loginWidget);
                        if (existingToken) {
                            // Widget exists, just reset it
                            window.turnstile.reset(loginWidget);
                            turnstileWidgetIds.login = loginWidget;
                        } else {
                            // Widget doesn't exist, render it
                            const widgetId = window.turnstile.render(loginWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.login = widgetId || loginWidget;
                        }
                    } catch (e) {
                        // Widget might not be rendered yet, so render it
                        try {
                            const widgetId = window.turnstile.render(loginWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.login = widgetId || loginWidget;
                        } catch (renderError) {
                            console.error('Error rendering Turnstile:', renderError);
                        }
                    }
                } else {
                    // Wait for Turnstile to load
                    setTimeout(renderWidget, 100);
                }
            };
            renderWidget();
        } else {
            // Hide widget if no site key
            loginWidget.style.display = 'none';
        }
    }
    
    if (!skipURLUpdate) {
        updateURL('/login', false); // Use pushState for navigation
    }
}

function showForgotPassword(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('forgotPasswordSection').style.display = 'block';
    if (!skipURLUpdate) {
        updateURL('/forgot-password', false);
    }
}

function showResetPassword(token, skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('resetPasswordSection').style.display = 'block';
    document.getElementById('resetToken').value = token;
    if (!skipURLUpdate) {
        updateURL(`/reset-password?token=${encodeURIComponent(token)}`, false);
    }
}

async function handleResetPasswordPage(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('resetPasswordSection').style.display = 'block';
    
    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (token) {
        document.getElementById('resetToken').value = token;
    } else {
        // No token in URL, show error
        document.getElementById('resetPasswordSection').innerHTML = `
            <div class="auth-card">
                <h2>Reset Password</h2>
                <div style="text-align: center; padding: 2rem;">
                    <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                    <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Invalid Reset Link</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        The password reset link is invalid or missing. Please request a new password reset.
                    </p>
                    <a href="#" onclick="showForgotPassword(); return false;" class="btn btn-primary">Request New Reset Link</a>
                </div>
            </div>
        `;
    }
    
    if (!skipURLUpdate) {
        updateURL('/reset-password' + (token ? `?token=${encodeURIComponent(token)}` : ''), false);
    }
}

function showRegister(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('registerSection').style.display = 'block';
    
    // Clear university field and validation message when showing register form
    const universityInput = document.getElementById('registerUniversity');
    const messageEl = document.getElementById('emailValidationMessage');
    if (universityInput) universityInput.value = '';
    if (messageEl) messageEl.style.display = 'none';
    
    // Ensure Turnstile widget is properly initialized
    const registerWidget = document.getElementById('turnstile-register');
    if (registerWidget) {
        if (turnstileSiteKey) {
            // Make sure widget is visible
            registerWidget.style.display = 'block';
            // Set site key if not already set
            if (!registerWidget.getAttribute('data-sitekey')) {
                registerWidget.setAttribute('data-sitekey', turnstileSiteKey);
            }
            
            // Wait a bit for Turnstile script to load, then render
            const renderWidget = () => {
                if (window.turnstile) {
                    try {
                        // Check if widget is already rendered by trying to get response
                        const existingToken = window.turnstile.getResponse(registerWidget);
                        if (existingToken) {
                            // Widget exists, just reset it
                            window.turnstile.reset(registerWidget);
                            turnstileWidgetIds.register = registerWidget;
                        } else {
                            // Widget doesn't exist, render it
                            const widgetId = window.turnstile.render(registerWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.register = widgetId || registerWidget;
                        }
                    } catch (e) {
                        // Widget might not be rendered yet, so render it
                        try {
                            const widgetId = window.turnstile.render(registerWidget, {
                                sitekey: turnstileSiteKey,
                                theme: 'light'
                            });
                            turnstileWidgetIds.register = widgetId || registerWidget;
                        } catch (renderError) {
                            console.error('Error rendering Turnstile:', renderError);
                        }
                    }
                } else {
                    // Wait for Turnstile to load
                    setTimeout(renderWidget, 100);
                }
            };
            renderWidget();
        } else {
            // Hide widget if no site key
            registerWidget.style.display = 'none';
        }
    }
    
    if (!skipURLUpdate) {
        updateURL('/register', false); // Use pushState for navigation
    }
}

function showVerification(email = null) {
    hideAllSections();
    document.getElementById('verificationSection').style.display = 'block';
    const content = document.getElementById('verificationContent');
    if (email) {
        content.innerHTML = `
            <div style="text-align: center; margin-bottom: 2rem;">
                <div style="font-size: 3rem; margin-bottom: 1rem;">📧</div>
                <h3 style="margin-bottom: 1rem;">Check Your Email</h3>
                <p style="color: var(--text-secondary); margin-bottom: 1rem;">
                    We've sent a verification email to <strong>${escapeHtml(email)}</strong>
                </p>
                <p style="color: var(--text-secondary); font-size: 0.875rem;">
                    Click the link in the email to verify your account and start using Rilono.
                </p>
            </div>
            <div style="text-align: center;">
                <button onclick="resendVerificationEmail('${escapeHtml(email)}')" class="btn btn-primary">Resend Verification Email</button>
                <p style="margin-top: 1rem;">
                    <a href="#" onclick="showLogin(); return false;">Back to Login</a>
                </p>
            </div>
        `;
    }
    updateURL('/verify-email', false);
}

async function handleEmailVerification(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('verificationSection').style.display = 'block';
    
    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (token) {
        // Verify the token
        try {
            const response = await fetch(`${API_BASE}/api/auth/verify-email?token=${encodeURIComponent(token)}`);
            const data = await response.json();
            
            if (response.ok) {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h3 style="margin-bottom: 1rem; color: var(--success-color);">Email Verified!</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            Your email has been successfully verified. You can now log in to your account.
                        </p>
                        <a href="#" onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</a>
                    </div>
                `;
            } else {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                        <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Verification Failed</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            ${escapeHtml(data.detail || 'Invalid or expired verification token.')}
                        </p>
                        <button onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</button>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Verification error:', error);
            document.getElementById('verificationContent').innerHTML = `
                <div style="text-align: center;">
                    <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                    <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Error</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        An error occurred during verification. Please try again.
                    </p>
                    <button onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</button>
                </div>
            `;
        }
    } else {
        // No token, show resend option
        showVerification();
    }
    
    if (!skipURLUpdate) {
        updateURL('/verify-email' + (token ? `?token=${token}` : ''), false);
    }
}

async function handleUniversityChangeVerification(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('verificationSection').style.display = 'block';
    
    // Get token from URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    
    if (token) {
        // Show loading
        document.getElementById('verificationContent').innerHTML = `
            <div style="text-align: center;">
                <div style="font-size: 4rem; margin-bottom: 1rem;">⏳</div>
                <h3 style="margin-bottom: 1rem;">Verifying University Change...</h3>
                <p style="color: var(--text-secondary);">Please wait while we verify your request.</p>
            </div>
        `;
        
        // Verify the token
        try {
            const response = await fetch(`${API_BASE}/api/auth/verify-university-change?token=${encodeURIComponent(token)}`);
            const data = await response.json();
            
            if (response.ok) {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem;">🎓</div>
                        <h3 style="margin-bottom: 1rem; color: var(--success-color);">University Changed!</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">
                            Your university has been successfully updated.
                        </p>
                        <div style="background: var(--bg-tertiary); padding: 1.5rem; border-radius: 12px; margin-bottom: 2rem; text-align: left;">
                            <p style="margin: 0.5rem 0;"><strong>New University:</strong> ${escapeHtml(data.new_university)}</p>
                            <p style="margin: 0.5rem 0;"><strong>New Email:</strong> ${escapeHtml(data.new_email)}</p>
                        </div>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem; font-size: 0.9rem;">
                            Please log in again with your new email address.
                        </p>
                        <a href="#" onclick="logout(); showLogin(); return false;" class="btn btn-primary">Login with New Email</a>
                    </div>
                `;
            } else {
                document.getElementById('verificationContent').innerHTML = `
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                        <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Verification Failed</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            ${escapeHtml(data.detail || 'Invalid or expired verification token.')}
                        </p>
                        <button onclick="showDashboard(); return false;" class="btn btn-primary">Go to Dashboard</button>
                    </div>
                `;
            }
        } catch (error) {
            console.error('University change verification error:', error);
            document.getElementById('verificationContent').innerHTML = `
                <div style="text-align: center;">
                    <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                    <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Error</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                        An error occurred during verification. Please try again.
                    </p>
                    <button onclick="showDashboard(); return false;" class="btn btn-primary">Go to Dashboard</button>
                </div>
            `;
        }
    } else {
        // No token
        document.getElementById('verificationContent').innerHTML = `
            <div style="text-align: center;">
                <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--danger-color);">✗</div>
                <h3 style="margin-bottom: 1rem; color: var(--danger-color);">Invalid Link</h3>
                <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                    This verification link is invalid. Please request a new university change from your profile.
                </p>
                <button onclick="showDashboard(); return false;" class="btn btn-primary">Go to Dashboard</button>
            </div>
        `;
    }
    
    if (!skipURLUpdate) {
        updateURL('/verify-university-change' + (token ? `?token=${token}` : ''), false);
    }
}

async function resendVerificationEmail(email = null) {
    if (!email) {
        email = prompt('Please enter your email address:');
        if (!email) return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/resend-verification`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email: email })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Verification email sent successfully!', 'success');
            showVerification(email);
        } else {
            showMessage(data.detail || 'Failed to send verification email', 'error');
        }
    } catch (error) {
        console.error('Resend verification error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

function showMarketplace(skipURLUpdate = false) {
    showHomepage(skipURLUpdate);
}

function showMarketplaceWithFilters(params, skipURLUpdate = false) {
    showHomepage(skipURLUpdate);
}

function showCreateItem(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showMyListings(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showMessages(skipURLUpdate = false) {
    showDashboard(skipURLUpdate);
}

function showDashboard(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to view dashboard', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('dashboardSection').style.display = 'block';
    loadProfile();
    loadDashboardStats();
    initializeRilonoAiChat();
    initializeYearDropdown();
    loadDocumentationPreferences();
    loadMyDocuments();
    
    // Set default tab to overview if no tab is active
    const activeTab = document.querySelector('.dashboard-tab.active');
    if (!activeTab) {
        switchDashboardTab('overview');
    }
    
    if (!skipURLUpdate) {
        updateURL('/dashboard', false); // Use pushState for navigation
    }
}

function switchDashboardTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.dashboard-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all nav items
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`dashboardTab-${tabName}`);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }
    
    // Activate corresponding nav item
    const navItem = document.querySelector(`.nav-item[data-tab="${tabName}"]`);
    if (navItem) {
        navItem.classList.add('active');
    }
    
    // Load data for specific tabs
    if (tabName === 'documents') {
        loadMyDocuments();
    } else if (tabName === 'overview') {
        loadDashboardStats();
    } else if (tabName === 'records') {
        initializeRilonoAiChat();
    }
    
    // Scroll to top of dashboard content
    const dashboardContent = document.querySelector('.dashboard-content');
    if (dashboardContent) {
        dashboardContent.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function showPrivacy(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('privacySection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/privacy', false);
    }
}

function showPricing(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('pricingSection').style.display = 'block';
    initializePricingSelector();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/pricing', false);
    }
}

function initializePricingSelector() {
    const countrySelect = document.getElementById('pricingCountrySelect');
    if (!countrySelect) return;

    const savedCountry = localStorage.getItem('pricingCountry');
    const countryCode = PRICING_COUNTRY_CONFIG[savedCountry] ? savedCountry : 'US';
    countrySelect.value = countryCode;
    updatePricingByCountry(countryCode);
}

function handlePricingCountryChange(countryCode) {
    if (!PRICING_COUNTRY_CONFIG[countryCode]) {
        countryCode = 'US';
    }
    localStorage.setItem('pricingCountry', countryCode);
    updatePricingByCountry(countryCode);
}

function updatePricingByCountry(countryCode) {
    const config = PRICING_COUNTRY_CONFIG[countryCode] || PRICING_COUNTRY_CONFIG.US;
    const freePriceEl = document.getElementById('pricingFreePrice');
    const proPriceEl = document.getElementById('pricingProPrice');
    const hintEl = document.getElementById('pricingCurrencyHint');

    const convertedFree = PRICING_BASE_USD.free * config.rate;
    const convertedPro = PRICING_BASE_USD.pro * config.rate;

    if (freePriceEl) {
        freePriceEl.innerHTML = `${formatCurrencyAmount(convertedFree, config.currency)}<span>/month</span>`;
    }
    if (proPriceEl) {
        proPriceEl.innerHTML = `${formatCurrencyAmount(convertedPro, config.currency)}<span>/month</span>`;
    }
    if (hintEl) {
        hintEl.textContent = `Currency: ${config.currency} (${config.country})`;
    }
}

function formatCurrencyAmount(amount, currencyCode) {
    try {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: currencyCode,
            maximumFractionDigits: currencyCode === 'JPY' ? 0 : 2
        }).format(amount);
    } catch (error) {
        return `$${amount.toFixed(2)}`;
    }
}

function showTerms(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('termsSection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/terms', false);
    }
}

function showContact(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('contactSection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    
    // Pre-fill email if user is logged in
    if (currentUser) {
        const emailField = document.getElementById('contactEmail');
        const nameField = document.getElementById('contactName');
        const userTypeField = document.getElementById('contactUserType');
        
        if (emailField && currentUser.email) {
            emailField.value = currentUser.email;
        }
        if (nameField && currentUser.full_name) {
            nameField.value = currentUser.full_name;
        }
        if (userTypeField) {
            userTypeField.value = 'student';
        }
    }
    
    if (!skipURLUpdate) {
        updateURL('/contact', false);
    }
}

async function handleContactSubmit(e) {
    e.preventDefault();
    
    const name = document.getElementById('contactName').value.trim();
    const email = document.getElementById('contactEmail').value.trim();
    const userType = document.getElementById('contactUserType').value;
    const subject = document.getElementById('contactSubject').value.trim();
    const message = document.getElementById('contactMessage').value.trim();
    const submitBtn = document.getElementById('contactSubmitBtn');
    
    // Validation
    if (!name || name.length < 2) {
        showMessage('Please enter your name', 'error');
        return;
    }
    
    if (!email || !email.includes('@')) {
        showMessage('Please enter a valid email address', 'error');
        return;
    }
    
    if (!subject || subject.length < 3) {
        showMessage('Please enter a subject', 'error');
        return;
    }
    
    if (!message || message.length < 10) {
        showMessage('Please enter a message (at least 10 characters)', 'error');
        return;
    }
    
    // Disable button and show loading state
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>Sending...</span>';
    
    try {
        const formData = new FormData();
        formData.append('name', name);
        formData.append('email', email);
        formData.append('user_type', userType);
        formData.append('subject', subject);
        formData.append('message', message);
        
        const response = await fetch(`${API_BASE}/api/auth/contact`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Message sent successfully! We\'ll get back to you soon.', 'success');
            // Clear the form
            document.getElementById('contactForm').reset();
            // Re-fill email/name if logged in
            if (currentUser) {
                if (currentUser.email) document.getElementById('contactEmail').value = currentUser.email;
                if (currentUser.full_name) document.getElementById('contactName').value = currentUser.full_name;
                document.getElementById('contactUserType').value = 'student';
            }
        } else {
            showMessage(data.detail || 'Failed to send message. Please try again.', 'error');
        }
    } catch (error) {
        console.error('Contact form error:', error);
        showMessage('Failed to send message. Please try again or email us directly at contact@rilono.com', 'error');
    } finally {
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>Send Message</span>';
    }
}

async function showItemDetail(itemId, skipURLUpdate = false) {
    showMessage('That page is no longer available.', 'error');
    showHomepage(skipURLUpdate);
}

function hideAllSections() {
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
}

// Auth functions
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;

    if (!email || !password) {
        showMessage('Please enter both email and password', 'error');
        return;
    }

    // Get Turnstile token (only if Turnstile is configured)
    let turnstileToken = null;
    if (turnstileSiteKey && window.turnstile) {
        try {
            // Try to get token using stored widget ID or element
            const loginWidget = document.getElementById('turnstile-login');
            if (loginWidget) {
                // Use the element directly (more reliable than ID string)
                turnstileToken = window.turnstile.getResponse(loginWidget);
            }
            
            // Fallback: try using stored widget ID
            if (!turnstileToken && turnstileWidgetIds.login) {
                turnstileToken = window.turnstile.getResponse(turnstileWidgetIds.login);
            }
            
            // Last fallback: try using ID string
            if (!turnstileToken) {
                turnstileToken = window.turnstile.getResponse('turnstile-login');
            }
            
            if (!turnstileToken) {
                showMessage('Please complete the security verification', 'error');
                return;
            }
        } catch (error) {
            console.error('Turnstile error:', error);
            showMessage('Please complete the security verification', 'error');
            return;
        }
    }

    try {
        const formData = new URLSearchParams();
        formData.append('username', email);  // OAuth2PasswordRequestForm expects 'username' field, but we use it for email
        formData.append('password', password);
        if (turnstileToken) {
            formData.append('cf_turnstile_token', turnstileToken);
        }

        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            authToken = data.access_token;
            localStorage.setItem('authToken', authToken);
            await checkAuth();
            showMessage('Login successful!', 'success');
            document.getElementById('loginForm').reset();
            // Reset Turnstile widget
            if (window.turnstile) {
                const loginWidget = document.getElementById('turnstile-login');
                if (loginWidget) {
                    try {
                        window.turnstile.reset(loginWidget);
                    } catch (e) {
                        // Ignore reset errors
                    }
                }
            }
            showDashboard();
        } else {
            let errorMessage = 'Login failed';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            
            // Check if it's an email verification error
            if (data.detail && data.detail.includes('verify your email')) {
                const email = document.getElementById('loginEmail').value.trim();
                showMessage(errorMessage, 'error');
                // Show option to resend verification
                setTimeout(() => {
                    if (confirm('Would you like to resend the verification email?')) {
                        resendVerificationEmail(email);
                    }
                }, 2000);
            } else {
                showMessage(errorMessage, 'error');
            }
        }
    } catch (error) {
        console.error('Login error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

async function handleRegister(e) {
    e.preventDefault();
    
    // Get form values and convert empty strings to null
    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };
    
    const userData = {
        email: getValue('registerEmail'),
        password: getValue('registerPassword'),
        full_name: getValue('registerFullName'),
        university: getValue('registerUniversity'),
        phone: getValue('registerPhone')
        // Username is optional - will be auto-generated from email on backend
    };

    // Validate required fields
    if (!userData.email || !userData.password) {
        showMessage('Please fill in all required fields (Email, Password)', 'error');
        return;
    }
    
    // Validate that university email domain is valid
    const universityInput = document.getElementById('registerUniversity');
    if (!universityInput.value.trim()) {
        showMessage('Please use a valid university email address. The email domain must be from a recognized university.', 'error');
        // Re-check the email to show validation message
        await checkUniversityByEmail(userData.email);
        return;
    }
    
    // Validate password length (bcrypt has 72-byte limit, but we handle longer passwords)
    // Still recommend reasonable length for security
    if (userData.password.length < 6) {
        showMessage('Password must be at least 6 characters long', 'error');
        return;
    }
    if (userData.password.length > 200) {
        showMessage('Password is too long. Please use a password less than 200 characters.', 'error');
        return;
    }

    // Get Turnstile token (only if Turnstile is configured)
    let turnstileToken = null;
    if (turnstileSiteKey && window.turnstile) {
        try {
            // Try to get token using stored widget ID or element
            const registerWidget = document.getElementById('turnstile-register');
            if (registerWidget) {
                // Use the element directly (more reliable than ID string)
                turnstileToken = window.turnstile.getResponse(registerWidget);
            }
            
            // Fallback: try using stored widget ID
            if (!turnstileToken && turnstileWidgetIds.register) {
                turnstileToken = window.turnstile.getResponse(turnstileWidgetIds.register);
            }
            
            // Last fallback: try using ID string
            if (!turnstileToken) {
                turnstileToken = window.turnstile.getResponse('turnstile-register');
            }
            
            if (!turnstileToken) {
                showMessage('Please complete the security verification', 'error');
                return;
            }
        } catch (error) {
            console.error('Turnstile error:', error);
            showMessage('Please complete the security verification', 'error');
            return;
        }
    }
    
    if (turnstileToken) {
        userData.cf_turnstile_token = turnstileToken;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(userData)
        });

        const data = await response.json();

        if (response.ok) {
            const email = userData.email;
            showMessage('Registration successful! Please check your email to verify your account.', 'success');
            document.getElementById('registerForm').reset();
            // Reset Turnstile widget
            if (window.turnstile) {
                const registerWidget = document.getElementById('turnstile-register');
                if (registerWidget) {
                    try {
                        window.turnstile.reset(registerWidget);
                    } catch (e) {
                        // Ignore reset errors
                    }
                }
            }
            showVerification(email);
        } else {
            // Handle different error formats
            let errorMessage = 'Registration failed';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    // Pydantic validation errors
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Registration error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

function logout() {
    localStorage.removeItem('authToken');
    authToken = null;
    currentUser = null;
    floatingChatOpen = false;
    rilonoAiConversationHistory = [];  // Clear shared chat history
    document.getElementById('floatingChatWindow').style.display = 'none';
    // Clear floating chat messages
    const floatingMessages = document.getElementById('floatingChatMessages');
    if (floatingMessages) floatingMessages.innerHTML = '';
    // Clear main chat messages in all dashboard chat panels
    getMainChatContainers().forEach((mainMessages) => {
        const existingMsgs = mainMessages.querySelectorAll('.rilono-ai-message');
        existingMsgs.forEach(msg => msg.remove());
    });
    updateUIForAuth();
    showMessage('Logged out successfully', 'success');
    showHomepage();
}

async function handleForgotPassword(e) {
    e.preventDefault();
    const email = document.getElementById('forgotPasswordEmail').value.trim();
    
    if (!email) {
        showMessage('Please enter your email address', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/forgot-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email: email })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Password reset link has been sent to your email.', 'success');
            // Show success message in the form
            document.getElementById('forgotPasswordSection').innerHTML = `
                <div class="auth-card">
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h2 style="margin-bottom: 1rem;">Check Your Email</h2>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            We've sent a password reset link to <strong>${escapeHtml(email)}</strong>. 
                            Please check your inbox.
                        </p>
                        <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 2rem;">
                            The link will expire in 1 hour.
                        </p>
                        <a href="#" onclick="showLogin(); return false;" class="btn btn-primary">Back to Login</a>
                    </div>
                </div>
            `;
        } else {
            let errorMessage = data.detail || 'Failed to send password reset email';
            
            // If account doesn't exist, show helpful message with link to register
            if (response.status === 404) {
                showMessage(errorMessage, 'error');
                // Show option to create account
                setTimeout(() => {
                    const forgotSection = document.getElementById('forgotPasswordSection');
                    if (forgotSection) {
                        const errorDiv = document.createElement('div');
                        errorDiv.style.marginTop = '1rem';
                        errorDiv.style.textAlign = 'center';
                        errorDiv.innerHTML = `
                            <p style="color: var(--text-secondary); margin-bottom: 1rem;">
                                Don't have an account?
                            </p>
                            <a href="#" onclick="showRegister(); return false;" class="btn btn-primary">Create Account</a>
                        `;
                        forgotSection.querySelector('.auth-card').appendChild(errorDiv);
                    }
                }, 100);
            } else {
                showMessage(errorMessage, 'error');
            }
        }
    } catch (error) {
        console.error('Forgot password error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

async function handleResetPassword(e) {
    e.preventDefault();
    const token = document.getElementById('resetToken').value;
    const newPassword = document.getElementById('resetPasswordNew').value;
    const confirmPassword = document.getElementById('resetPasswordConfirm').value;
    
    if (!token) {
        showMessage('Invalid reset token', 'error');
        return;
    }
    
    if (!newPassword || newPassword.length < 6) {
        showMessage('Password must be at least 6 characters long', 'error');
        return;
    }
    
    if (newPassword !== confirmPassword) {
        showMessage('Passwords do not match', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/reset-password`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                token: token,
                new_password: newPassword
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage(data.message || 'Password reset successfully! You can now log in.', 'success');
            // Show success and redirect to login
            document.getElementById('resetPasswordSection').innerHTML = `
                <div class="auth-card">
                    <div style="text-align: center;">
                        <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--success-color);">✓</div>
                        <h2 style="margin-bottom: 1rem; color: var(--success-color);">Password Reset Successful!</h2>
                        <p style="color: var(--text-secondary); margin-bottom: 2rem;">
                            Your password has been reset successfully. You can now log in with your new password.
                        </p>
                        <a href="#" onclick="showLogin(); return false;" class="btn btn-primary">Go to Login</a>
                    </div>
                </div>
            `;
            // Auto-redirect to login after 3 seconds
            setTimeout(() => {
                showLogin();
            }, 3000);
        } else {
            let errorMessage = 'Failed to reset password';
            if (data.detail) {
                errorMessage = data.detail;
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Reset password error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

// Item functions
async function loadItems(skipURLUpdate = false) {
    if (!document.getElementById('marketplaceSection')) {
        return;
    }
    const search = document.getElementById('searchInput')?.value || '';
    const category = document.getElementById('categoryFilter')?.value || '';
    const minPrice = document.getElementById('minPrice')?.value || '';
    const maxPrice = document.getElementById('maxPrice')?.value || '';

    // Update URL with current search filters (only if not handling back/forward)
    if (!skipURLUpdate) {
        const searchURL = buildSearchURL(search.trim(), category, minPrice, maxPrice);
        updateURL('/' + (searchURL ? '?' + searchURL : ''), false);
    }

    let url = `${API_BASE}/api/items/?`;
    const params = new URLSearchParams();
    if (search.trim()) params.append('search', search.trim());
    if (category) params.append('category', category);
    if (minPrice) params.append('min_price', minPrice);
    if (maxPrice) params.append('max_price', maxPrice);
    
    url += params.toString();

    try {
        const response = await fetch(url);
        if (response.ok) {
            const items = await response.json();
            displayItems(items, 'itemsGrid');
        } else {
            const error = await response.json().catch(() => ({}));
            showMessage(error.detail || 'Failed to load items', 'error');
        }
    } catch (error) {
        console.error('Load items error:', error);
        showMessage('An error occurred while loading items. Please check your connection.', 'error');
    }
}

async function loadMyItems() {
    if (!authToken) return;

    try {
        const response = await fetch(`${API_BASE}/api/items/my/listings`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const items = await response.json();
            displayItems(items, 'myItemsGrid', true);
        } else {
            const error = await response.json().catch(() => ({}));
            if (response.status === 401) {
                showMessage('Session expired. Please login again.', 'error');
                logout();
            } else {
                showMessage(error.detail || 'Failed to load your items', 'error');
            }
        }
    } catch (error) {
        console.error('Load my items error:', error);
        showMessage('An error occurred while loading your items. Please check your connection.', 'error');
    }
}

function getImageUrl(imageUrl) {
    if (!imageUrl) return null;
    if (imageUrl.startsWith('http') || imageUrl.startsWith('/')) {
        return imageUrl;
    }
    return API_BASE + (imageUrl.startsWith('/') ? '' : '/') + imageUrl;
}

function displayItems(items, containerId, showActions = false) {
    const container = document.getElementById(containerId);
    if (items.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); grid-column: 1 / -1;">No items found.</p>';
        return;
    }

    container.innerHTML = items.map((item, itemIndex) => {
        // Get images - prefer new images array, fallback to image_url
        const images = item.images && item.images.length > 0 
            ? item.images.map(img => img.image_url)
            : (item.image_url ? [item.image_url] : []);
        
        const firstImage = images.length > 0 ? images[0] : null;
        const imageUrl = firstImage ? getImageUrl(firstImage) : null;
        const imageCount = images.length;
        
        // Store images in a global map for easy access
        const imageKey = `item_${item.id}_${itemIndex}`;
        if (!window.itemImagesMap) {
            window.itemImagesMap = {};
        }
        window.itemImagesMap[imageKey] = images.map(img => getImageUrl(img));
        
        return `
        <div class="item-card" style="cursor: pointer;" onclick="showItemDetail(${item.id})" data-item-id="${item.id}">
            <div class="item-image" style="position: relative; cursor: ${imageCount > 0 ? 'pointer' : 'default'};" ${imageCount > 0 ? `data-image-key="${imageKey}" data-item-id="${item.id}" data-item-title="${escapeHtml(item.title)}" onclick="event.stopPropagation(); handleItemImageClick(this)"` : ''}>
                ${imageUrl ? `<img src="${imageUrl}" alt="${item.title}" style="width: 100%; height: 100%; object-fit: cover; pointer-events: none;" onerror="this.parentElement.innerHTML='📦';">` : '📦'}
                ${imageCount > 1 ? `<div style="position: absolute; bottom: 0.5rem; right: 0.5rem; background: rgba(0,0,0,0.7); color: white; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.875rem; pointer-events: none;">${imageCount} photos</div>` : ''}
            </div>
            <div class="item-content">
                ${item.is_sold ? '<span class="sold-badge">SOLD</span>' : ''}
                <div class="item-title">${escapeHtml(item.title)}</div>
                <div class="item-price">$${item.price.toFixed(2)}${item.category === 'sublease' ? ' /month' : ''}</div>
                ${item.category ? `<span class="item-category">${escapeHtml(item.category)}</span>` : ''}
                ${item.description ? `<div class="item-description">${escapeHtml(item.description)}</div>` : ''}
                ${item.address ? `<div class="item-location" style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">📍 ${escapeHtml(item.address)}</div>` : ''}
                <div class="item-seller">Seller: ${escapeHtml(item.seller.username)}</div>
                ${showActions && !item.is_sold ? `
                    <div class="item-actions" onclick="event.stopPropagation();">
                        <button class="btn btn-primary" onclick="editItem(${item.id})">Edit</button>
                        <button class="btn btn-primary" onclick="markAsSold(${item.id})">Mark as Sold</button>
                        <button class="btn btn-danger" onclick="deleteItem(${item.id})">Delete</button>
                    </div>
                ` : !item.is_sold && (!currentUser || currentUser.id !== item.seller_id) ? `
                    <div class="item-actions" onclick="event.stopPropagation();">
                        <button class="btn btn-primary" onclick="startConversation(${item.id}, ${item.seller_id})">Message Seller</button>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
    }).join('');
}

// Store selected images (files and URLs)
let selectedImages = [];

function handleMultipleImagePreview(e) {
    const files = Array.from(e.target.files);
    const previewsContainer = document.getElementById('imagePreviews');
    
    if (files.length === 0) {
        return;
    }
    
    // Limit to 10 images
    if (files.length > 10) {
        showMessage('Maximum 10 images allowed', 'error');
        e.target.value = '';
        return;
    }
    
    // Validate and add files
    files.forEach((file, index) => {
        // Validate file type
        if (!file.type.startsWith('image/')) {
            showMessage(`File ${index + 1} is not an image`, 'error');
            return;
        }
        
        // Validate file size (5MB)
        if (file.size > 5 * 1024 * 1024) {
            showMessage(`Image ${index + 1} is too large (max 5MB)`, 'error');
            return;
        }
        
        // Add to selected images
        const imageId = `img_${Date.now()}_${index}`;
        selectedImages.push({
            id: imageId,
            file: file,
            type: 'file',
            url: null
        });
        
        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            addImagePreview(imageId, e.target.result, 'file');
        };
        reader.readAsDataURL(file);
    });
    
    previewsContainer.style.display = 'grid';
}


function addImagePreview(imageId, src, type) {
    const previewsContainer = document.getElementById('imagePreviews');
    const previewDiv = document.createElement('div');
    previewDiv.id = `preview_${imageId}`;
    previewDiv.style.position = 'relative';
    previewDiv.style.aspectRatio = '1';
    previewDiv.style.overflow = 'hidden';
    previewDiv.style.borderRadius = '0.5rem';
    previewDiv.style.border = '2px solid var(--border-color)';
    
    const img = document.createElement('img');
    img.src = src;
    img.style.width = '100%';
    img.style.height = '100%';
    img.style.objectFit = 'cover';
    img.onerror = () => {
        previewDiv.remove();
        selectedImages = selectedImages.filter(img => img.id !== imageId);
        showMessage('Failed to load image', 'error');
    };
    
    const removeBtn = document.createElement('button');
    removeBtn.textContent = '×';
    removeBtn.type = 'button';
    removeBtn.style.position = 'absolute';
    removeBtn.style.top = '0.25rem';
    removeBtn.style.right = '0.25rem';
    removeBtn.style.width = '2rem';
    removeBtn.style.height = '2rem';
    removeBtn.style.borderRadius = '50%';
    removeBtn.style.border = 'none';
    removeBtn.style.background = 'var(--danger-color)';
    removeBtn.style.color = 'white';
    removeBtn.style.cursor = 'pointer';
    removeBtn.style.fontSize = '1.25rem';
    removeBtn.style.fontWeight = 'bold';
    removeBtn.onclick = () => removeImage(imageId);
    
    previewDiv.appendChild(img);
    previewDiv.appendChild(removeBtn);
    previewsContainer.appendChild(previewDiv);
}

function removeImage(imageId) {
    selectedImages = selectedImages.filter(img => img.id !== imageId);
    const preview = document.getElementById(`preview_${imageId}`);
    if (preview) {
        preview.remove();
    }
    
    const previewsContainer = document.getElementById('imagePreviews');
    if (selectedImages.length === 0) {
        previewsContainer.style.display = 'none';
    }
}

let addressAutocomplete = null;

function initializeAddressAutocomplete() {
    const addressInput = document.getElementById('itemAddress');
    if (!addressInput) return;
    
    // Check if Google Maps API is loaded
    const checkGoogleMaps = () => {
        if (typeof google !== 'undefined' && google.maps && google.maps.places) {
            // Initialize Google Places Autocomplete
            addressAutocomplete = new google.maps.places.Autocomplete(addressInput, {
                types: ['address'],
                fields: ['formatted_address', 'address_components', 'geometry']
            });
            
            // Handle place selection
            addressAutocomplete.addListener('place_changed', () => {
                const place = addressAutocomplete.getPlace();
                
                if (!place.geometry) {
                    showMessage('No details available for the selected address', 'error');
                    return;
                }
                
                // Extract address components
                let city = '';
                let state = '';
                let zipCode = '';
                
                place.address_components.forEach(component => {
                    const types = component.types;
                    
                    if (types.includes('locality')) {
                        city = component.long_name;
                    } else if (types.includes('administrative_area_level_1')) {
                        state = component.short_name;
                    } else if (types.includes('postal_code')) {
                        zipCode = component.long_name;
                    }
                });
                
                // Update form fields
                document.getElementById('itemAddress').value = place.formatted_address;
                document.getElementById('itemCity').value = city;
                document.getElementById('itemState').value = state;
                document.getElementById('itemZipCode').value = zipCode;
                document.getElementById('itemLatitude').value = place.geometry.location.lat();
                document.getElementById('itemLongitude').value = place.geometry.location.lng();
                
                // Show address details
                document.getElementById('addressDetails').style.display = 'grid';
            });
        } else {
            // Fallback: Check again after a delay if API is still loading
            setTimeout(checkGoogleMaps, 500);
        }
    };
    
    // Start checking for Google Maps API
    checkGoogleMaps();
}

function initializeSearchableDropdowns() {
    // Initialize document type searchable dropdown
    const documentTypeDropdown = document.getElementById('documentTypeDropdown');
    if (!documentTypeDropdown) return;
    
    const searchInput = documentTypeDropdown.querySelector('.dropdown-search');
    const hiddenInput = documentTypeDropdown.querySelector('input[type="hidden"]');
    const dropdownList = documentTypeDropdown.querySelector('.dropdown-list');
    const items = dropdownList.querySelectorAll('.dropdown-item');
    
    // Open dropdown on focus
    searchInput.addEventListener('focus', () => {
        documentTypeDropdown.classList.add('open');
        filterItems('');
    });
    
    // Filter items on input
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        filterItems(searchTerm);
        
        // Clear selection if user is typing
        if (searchTerm) {
            hiddenInput.value = '';
            items.forEach(item => item.classList.remove('selected'));
        }
    });
    
    // Handle item selection
    items.forEach(item => {
        item.addEventListener('click', () => {
            const value = item.dataset.value;
            const text = item.textContent;
            
            searchInput.value = text;
            hiddenInput.value = value;
            
            // Update selected state
            items.forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            
            documentTypeDropdown.classList.remove('open');
        });
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!documentTypeDropdown.contains(e.target)) {
            documentTypeDropdown.classList.remove('open');
            
            // If no valid selection, clear the input
            if (!hiddenInput.value && searchInput.value) {
                // Try to find an exact match
                const matchingItem = Array.from(items).find(
                    item => item.textContent.toLowerCase() === searchInput.value.toLowerCase()
                );
                if (matchingItem) {
                    hiddenInput.value = matchingItem.dataset.value;
                    searchInput.value = matchingItem.textContent;
                    matchingItem.classList.add('selected');
                } else {
                    searchInput.value = '';
                }
            }
        }
    });
    
    // Handle keyboard navigation
    searchInput.addEventListener('keydown', (e) => {
        const visibleItems = Array.from(items).filter(item => !item.classList.contains('hidden'));
        const currentIndex = visibleItems.findIndex(item => item.classList.contains('highlighted'));
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!documentTypeDropdown.classList.contains('open')) {
                documentTypeDropdown.classList.add('open');
            }
            const nextIndex = currentIndex < visibleItems.length - 1 ? currentIndex + 1 : 0;
            highlightItem(visibleItems, nextIndex);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const prevIndex = currentIndex > 0 ? currentIndex - 1 : visibleItems.length - 1;
            highlightItem(visibleItems, prevIndex);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const highlightedItem = visibleItems.find(item => item.classList.contains('highlighted'));
            if (highlightedItem) {
                highlightedItem.click();
            } else if (visibleItems.length === 1) {
                visibleItems[0].click();
            }
        } else if (e.key === 'Escape') {
            documentTypeDropdown.classList.remove('open');
        }
    });
    
    function filterItems(searchTerm) {
        let hasResults = false;
        items.forEach(item => {
            const text = item.textContent.toLowerCase();
            const matches = text.includes(searchTerm);
            item.classList.toggle('hidden', !matches);
            if (matches) hasResults = true;
        });
        
        // Show "no results" message
        let noResultsEl = dropdownList.querySelector('.no-results');
        if (!hasResults) {
            if (!noResultsEl) {
                noResultsEl = document.createElement('div');
                noResultsEl.className = 'no-results';
                noResultsEl.textContent = 'No document types found';
                dropdownList.appendChild(noResultsEl);
            }
            noResultsEl.style.display = 'block';
        } else if (noResultsEl) {
            noResultsEl.style.display = 'none';
        }
    }
    
    function highlightItem(visibleItems, index) {
        items.forEach(item => item.classList.remove('highlighted'));
        if (visibleItems[index]) {
            visibleItems[index].classList.add('highlighted');
            visibleItems[index].scrollIntoView({ block: 'nearest' });
        }
    }
}

async function uploadImages(files) {
    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
    });
    
    const response = await fetch(`${API_BASE}/api/upload/images`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${authToken}`
        },
        body: formData
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to upload images');
    }
    
    const data = await response.json();
    return data.images.map(img => img.url);
}

async function editItem(itemId) {
    if (!authToken) {
        showMessage('Please login to edit items', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (!response.ok) {
            throw new Error('Failed to load item');
        }

        const item = await response.json();

        // Set editing mode
        document.getElementById('editingItemId').value = itemId;
        document.getElementById('itemFormTitle').textContent = 'Edit Item';
        document.getElementById('itemSubmitButton').textContent = 'Update Item';

        // Populate form fields
        document.getElementById('itemTitle').value = item.title || '';
        document.getElementById('itemDescription').value = item.description || '';
        document.getElementById('itemPrice').value = item.price || '';
        document.getElementById('itemCategory').value = item.category || '';
        document.getElementById('itemCondition').value = item.condition || '';
        document.getElementById('itemAddress').value = item.address || '';
        document.getElementById('itemCity').value = item.city || '';
        document.getElementById('itemState').value = item.state || '';
        document.getElementById('itemZipCode').value = item.zip_code || '';
        document.getElementById('itemLatitude').value = item.latitude || '';
        document.getElementById('itemLongitude').value = item.longitude || '';

        // Show address details if address exists
        if (item.address) {
            document.getElementById('addressDetails').style.display = 'grid';
        }

        // Update price label based on category
        updatePriceLabel();

        // Load existing images
        selectedImages = [];
        const images = item.images && item.images.length > 0 
            ? item.images.map(img => img.image_url)
            : (item.image_url ? [item.image_url] : []);

        const previewsContainer = document.getElementById('imagePreviews');
        previewsContainer.innerHTML = '';
        
        if (images.length > 0) {
            previewsContainer.style.display = 'grid';
            images.forEach((imageUrl, index) => {
                const imageId = `existing_${itemId}_${index}`;
                selectedImages.push({ id: imageId, src: imageUrl, type: 'url' });
                addImagePreview(imageId, imageUrl, 'url');
            });
        } else {
            previewsContainer.style.display = 'none';
        }

        // Show the create/edit form
        showCreateItem();
    } catch (error) {
        console.error('Edit item error:', error);
        showMessage('Failed to load item for editing', 'error');
    }
}

function resetItemForm() {
    document.getElementById('editingItemId').value = '';
    document.getElementById('itemFormTitle').textContent = 'List an Item for Sale';
    document.getElementById('itemSubmitButton').textContent = 'List Item';
    document.getElementById('createItemForm').reset();
    document.getElementById('imagePreviews').innerHTML = '';
    document.getElementById('imagePreviews').style.display = 'none';
    document.getElementById('addressDetails').style.display = 'none';
    selectedImages = [];
    updatePriceLabel();
}

async function handleCreateItem(e) {
    e.preventDefault();
    if (!authToken) {
        showMessage('Please login to list an item', 'error');
        return;
    }

    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };

    const title = getValue('itemTitle');
    const price = parseFloat(document.getElementById('itemPrice').value);
    const editingItemId = document.getElementById('editingItemId').value;

    if (!title || isNaN(price) || price < 0) {
        showMessage('Please fill in title and a valid price', 'error');
        return;
    }

    // Collect all image URLs
    let imageUrls = [];
    
    // Keep existing images (from URLs)
    const existingImages = selectedImages.filter(img => img.type === 'url').map(img => img.src);
    imageUrls.push(...existingImages);
    
    // Get files to upload
    const filesToUpload = selectedImages.filter(img => img.type === 'file').map(img => img.file);
    
    // Upload new files if any
    if (filesToUpload.length > 0) {
        try {
            showMessage(`Uploading ${filesToUpload.length} image(s)...`, 'success');
            const uploadedUrls = await uploadImages(filesToUpload);
            imageUrls.push(...uploadedUrls);
        } catch (error) {
            showMessage(error.message || 'Failed to upload images', 'error');
            return;
        }
    }

    // Get address data
    const address = getValue('itemAddress');
    const city = getValue('itemCity');
    const state = getValue('itemState');
    const zipCode = getValue('itemZipCode');
    const latitude = document.getElementById('itemLatitude').value ? parseFloat(document.getElementById('itemLatitude').value) : null;
    const longitude = document.getElementById('itemLongitude').value ? parseFloat(document.getElementById('itemLongitude').value) : null;

    const itemData = {
        title: title,
        description: getValue('itemDescription'),
        price: price,
        category: getValue('itemCategory'),
        condition: getValue('itemCondition'),
        image_urls: imageUrls.length > 0 ? imageUrls : null,
        image_url: imageUrls.length > 0 ? imageUrls[0] : null,  // Backward compatibility
        address: address,
        city: city,
        state: state,
        zip_code: zipCode,
        latitude: latitude,
        longitude: longitude
    };

    try {
        const url = editingItemId 
            ? `${API_BASE}/api/items/${editingItemId}`
            : `${API_BASE}/api/items/`;
        const method = editingItemId ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(itemData)
        });

        const data = await response.json();

        if (response.ok) {
            showMessage(editingItemId ? 'Item updated successfully!' : 'Item listed successfully!', 'success');
            resetItemForm();
            showMyListings();
            loadMyItems();
        } else {
            let errorMessage = editingItemId ? 'Failed to update item' : 'Failed to create item';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Create/Update item error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

async function markAsSold(itemId) {
    if (!authToken) return;

    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ is_sold: true })
        });

        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            showMessage('Item marked as sold!', 'success');
            loadMyItems();
        } else {
            let errorMessage = 'Failed to update item';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Mark as sold error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

async function deleteItem(itemId) {
    if (!authToken) return;
    if (!confirm('Are you sure you want to delete this item?')) return;

    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok || response.status === 204) {
            showMessage('Item deleted successfully!', 'success');
            loadMyItems();
        } else {
            const error = await response.json().catch(() => ({}));
            showMessage(error.detail || 'Failed to delete item', 'error');
        }
    } catch (error) {
        console.error('Delete item error:', error);
        showMessage('An error occurred. Please try again.', 'error');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Messaging functions
let currentConversation = null;

async function checkUnreadMessages() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/unread-count`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const data = await response.json();
            const badge = document.getElementById('unreadBadge');
            if (data.unread_count > 0) {
                badge.textContent = data.unread_count;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Failed to check unread messages:', error);
    }
}

async function loadConversations() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/conversations`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const conversations = await response.json();
            displayConversations(conversations);
        } else {
            showMessage('Failed to load conversations', 'error');
        }
    } catch (error) {
        console.error('Load conversations error:', error);
        showMessage('An error occurred while loading conversations', 'error');
    }
}

function displayConversations(conversations) {
    const container = document.getElementById('conversationsList');
    
    if (conversations.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); padding: 2rem;">No conversations yet. Start messaging sellers about items!</p>';
        return;
    }
    
    container.innerHTML = conversations.map(conv => {
        const lastMessage = conv.last_message;
        const preview = lastMessage ? (lastMessage.content.length > 50 ? lastMessage.content.substring(0, 50) + '...' : lastMessage.content) : 'No messages yet';
        const time = lastMessage ? formatTime(lastMessage.created_at) : '';
        const unreadClass = conv.unread_count > 0 ? 'unread' : '';
        
        // Get display name (full name if available, otherwise username)
        const displayName = conv.other_user.full_name || conv.other_user.username;
        const university = conv.other_user.university || '';
        
        const avatarContent = conv.other_user.profile_picture 
            ? `<img src="${getImageUrl(conv.other_user.profile_picture)}" alt="${escapeHtml(displayName)}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;">`
            : displayName.charAt(0).toUpperCase();
        
        return `
            <div class="conversation-item ${unreadClass}" onclick="openConversation(${conv.item.id}, ${conv.other_user.id}, '${escapeHtml(conv.other_user.username)}', '${escapeHtml(conv.item.title)}')">
                <div class="conversation-avatar">${avatarContent}</div>
                <div class="conversation-info">
                    <div class="conversation-header">
                        <div>
                            <span class="conversation-name">${escapeHtml(displayName)}</span>
                            ${university ? `<span style="font-size: 0.75rem; color: var(--text-secondary); margin-left: 0.5rem;">• ${escapeHtml(university)}</span>` : ''}
                        </div>
                        <span class="conversation-time">${time}</span>
                    </div>
                    <div class="conversation-preview">
                        <span class="conversation-item-title">${escapeHtml(conv.item.title)}</span>
                        <span class="conversation-message">${escapeHtml(preview)}</span>
                    </div>
                </div>
                ${conv.unread_count > 0 ? `<span class="unread-badge">${conv.unread_count}</span>` : ''}
            </div>
        `;
    }).join('');
}

async function openConversation(itemId, otherUserId, otherUsername, itemTitle) {
    currentConversation = { itemId, otherUserId, otherUsername, itemTitle };
    
    // Fetch other user details to show name and university
    let userDetails = '';
    try {
        const userResponse = await fetch(`${API_BASE}/api/auth/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (userResponse.ok) {
            const currentUserData = await userResponse.json();
            // Fetch the other user's details (we'll need to get this from the conversation or messages)
            // For now, we'll get it from the first message or conversation data
        }
    } catch (error) {
        console.error('Failed to fetch user details:', error);
    }
    
    // Update chat header - will be updated with full details after loading messages
    document.getElementById('chatHeaderInfo').innerHTML = `
        <div>
            <strong>${escapeHtml(otherUsername)}</strong>
            <div style="font-size: 0.875rem; color: var(--text-secondary);">${escapeHtml(itemTitle)}</div>
        </div>
    `;
    
    // Show delete button
    document.getElementById('deleteChatBtn').style.display = 'block';
    
    // Show chat, hide no chat selected
    document.getElementById('noChatSelected').style.display = 'none';
    document.getElementById('chatContainer').style.display = 'flex';
    
    // Load messages (which will include user details)
    await loadMessages(itemId, otherUserId);
    
    // Scroll to bottom
    scrollChatToBottom();
}

function closeChat() {
    document.getElementById('chatContainer').style.display = 'none';
    document.getElementById('noChatSelected').style.display = 'block';
    document.getElementById('deleteChatBtn').style.display = 'none';
    currentConversation = null;
}

async function handleDeleteConversation() {
    if (!currentConversation || !authToken) {
        return;
    }
    
    // First confirmation
    if (!confirm('Are you sure you want to delete this conversation? This action cannot be undone.')) {
        return;
    }
    
    // Second confirmation
    if (!confirm('This will permanently delete all messages in this conversation. Are you absolutely sure?')) {
        return;
    }
    
    try {
        const { itemId, otherUserId } = currentConversation;
        const response = await fetch(`${API_BASE}/api/messages/conversation/${itemId}/${otherUserId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok || response.status === 204) {
            showMessage('Conversation deleted successfully', 'success');
            // Close the chat
            closeChat();
            // Reload conversations list
            await loadConversations();
            // Update unread count
            await checkUnreadMessages();
        } else {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to delete conversation');
        }
    } catch (error) {
        console.error('Delete conversation error:', error);
        showMessage(error.message || 'An error occurred while deleting the conversation. Please try again.', 'error');
    }
}

async function loadMessages(itemId, otherUserId) {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/conversation/${itemId}/${otherUserId}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const messages = await response.json();
            displayMessages(messages);
            
            // Update chat header with user details from first message
            if (messages.length > 0) {
                const otherUser = messages[0].sender_id === otherUserId ? messages[0].sender : messages[0].receiver;
                updateChatHeader(otherUser, currentConversation.itemTitle);
                // Show delete button
                document.getElementById('deleteChatBtn').style.display = 'block';
            }
            
            checkUnreadMessages(); // Update badge
        } else {
            showMessage('Failed to load messages', 'error');
        }
    } catch (error) {
        console.error('Load messages error:', error);
        showMessage('An error occurred while loading messages', 'error');
    }
}

function updateChatHeader(otherUser, itemTitle) {
    if (!otherUser) return;
    
    const name = otherUser.full_name || otherUser.username;
    const university = otherUser.university || '';
    
    // Create avatar for header
    const avatarHtml = otherUser.profile_picture
        ? `<img src="${getImageUrl(otherUser.profile_picture)}" alt="${escapeHtml(name)}" style="width: 2.5rem; height: 2.5rem; border-radius: 50%; object-fit: cover; margin-right: 0.75rem; border: 2px solid var(--primary-color);">`
        : `<div style="width: 2.5rem; height: 2.5rem; border-radius: 50%; background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%); display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; margin-right: 0.75rem; border: 2px solid var(--primary-color);">${name.charAt(0).toUpperCase()}</div>`;
    
    document.getElementById('chatHeaderInfo').innerHTML = `
        <div style="display: flex; align-items: center;">
            ${avatarHtml}
            <div>
                <strong>${escapeHtml(name)}</strong>
                ${university ? `<div style="font-size: 0.875rem; color: var(--text-secondary);">${escapeHtml(university)}</div>` : ''}
                <div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.25rem;">${escapeHtml(itemTitle)}</div>
            </div>
        </div>
    `;
}


function displayMessages(messages) {
    const container = document.getElementById('chatMessages');
    
    if (messages.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); padding: 2rem;">No messages yet. Start the conversation!</p>';
        return;
    }
    
    container.innerHTML = messages.map(msg => {
        const isSent = msg.sender_id === currentUser.id;
        const time = formatTime(msg.created_at);
        
        return `
            <div class="message ${isSent ? 'sent' : 'received'}">
                <div class="message-content">
                    <div class="message-text">${escapeHtml(msg.content)}</div>
                    <div class="message-time">${time}</div>
                </div>
            </div>
        `;
    }).join('');
    
    scrollChatToBottom();
}

function toggleEmojiPicker() {
    const picker = document.getElementById('emojiPicker');
    picker.style.display = picker.style.display === 'none' ? 'block' : 'none';
}

function insertEmoji(emoji) {
    const input = document.getElementById('messageInput');
    const cursorPos = input.selectionStart || input.value.length;
    const textBefore = input.value.substring(0, cursorPos);
    const textAfter = input.value.substring(input.selectionEnd || cursorPos);
    input.value = textBefore + emoji + textAfter;
    input.focus();
    input.setSelectionRange(cursorPos + emoji.length, cursorPos + emoji.length);
    // Close emoji picker after selection
    document.getElementById('emojiPicker').style.display = 'none';
}

// Close emoji picker when clicking outside
document.addEventListener('click', (e) => {
    const picker = document.getElementById('emojiPicker');
    const emojiBtn = document.querySelector('.btn-emoji');
    if (picker && emojiBtn && !picker.contains(e.target) && !emojiBtn.contains(e.target)) {
        picker.style.display = 'none';
    }
});

async function sendMessage(e) {
    e.preventDefault();
    if (!authToken || !currentConversation) return;
    
    const input = document.getElementById('messageInput');
    const content = input.value.trim();
    
    if (!content) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/messages/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                item_id: currentConversation.itemId,
                receiver_id: currentConversation.otherUserId,
                content: content
            })
        });
        
        if (response.ok) {
            input.value = '';
            // Reload messages to show the new one
            await loadMessages(currentConversation.itemId, currentConversation.otherUserId);
            // Reload conversations to update last message
            await loadConversations();
        } else {
            const error = await response.json().catch(() => ({}));
            showMessage(error.detail || 'Failed to send message', 'error');
        }
    } catch (error) {
        console.error('Send message error:', error);
        showMessage('An error occurred while sending message', 'error');
    }
}

function startConversation(itemId, sellerId) {
    if (!currentUser) {
        showMessage('Please login to message sellers', 'error');
        showLogin();
        return;
    }
    
    if (currentUser.id === sellerId) {
        showMessage('You cannot message yourself', 'error');
        return;
    }
    
    // Redirect to messages page with query parameters
    window.location.href = `/messages?itemId=${itemId}&sellerId=${sellerId}`;
}

function scrollChatToBottom() {
    const container = document.getElementById('chatMessages');
    container.scrollTop = container.scrollHeight;
}

function formatTime(dateString) {
    if (!dateString) return 'Just now';
    
    // Parse the date string - FastAPI returns ISO 8601 format
    let date;
    try {
        // If date has no timezone info, JavaScript will parse it as local time
        // This is usually correct for server times stored in local timezone
        date = new Date(dateString);
        
        // If parsing failed, try adding UTC timezone
        if (isNaN(date.getTime())) {
            // Try treating as UTC if no timezone specified
            if (!dateString.includes('Z') && !dateString.match(/[+-]\d{2}:?\d{2}$/)) {
                date = new Date(dateString + 'Z');
            } else {
                // Try parsing as-is one more time
                date = new Date(dateString);
            }
        }
    } catch (e) {
        console.error('Error parsing date:', dateString, e);
        return 'Just now';
    }
    
    // Check if date is valid
    if (isNaN(date.getTime())) {
        console.error('Invalid date string:', dateString, 'Type:', typeof dateString);
        return 'Just now';
    }
    
    const now = new Date();
    let diff = now.getTime() - date.getTime();
    
    // If date appears to be in the future (more than 1 hour), likely timezone issue
    // Try parsing as local time without timezone
    if (diff < -3600000) { // More than 1 hour in the future
        try {
            // Remove timezone info and parse as local
            const localStr = dateString.replace(/Z$/, '').replace(/[+-]\d{2}:?\d{2}$/, '');
            const localDate = new Date(localStr);
            if (!isNaN(localDate.getTime())) {
                const localDiff = now.getTime() - localDate.getTime();
                if (localDiff >= 0) {
                    // Use the local time parsing
                    date = localDate;
                    diff = localDiff;
                }
            }
        } catch (e) {
            // Keep original date
        }
    }
    
    // If still in the future after correction, show as "Just now" to avoid confusion
    if (diff < 0) {
        console.warn('Date in future after parsing:', dateString, 'Parsed:', date.toISOString(), 'Now:', now.toISOString());
        return 'Just now';
    }
    
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    const weeks = Math.floor(days / 7);
    const months = Math.floor(days / 30);
    const years = Math.floor(days / 365);
    
    if (seconds < 60) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    if (weeks < 4) return `${weeks}w ago`;
    if (months < 12) return `${months}mo ago`;
    if (years >= 1) return `${years}y ago`;
    
    // For dates older than a year, show the actual date
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
}

// Profile functions
async function loadProfile() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        if (response.ok) {
            const profile = await response.json();
            displayProfile(profile);
        } else {
            showMessage('Failed to load profile', 'error');
        }
    } catch (error) {
        console.error('Load profile error:', error);
        showMessage('An error occurred while loading profile', 'error');
    }
}

function displayProfile(profile) {
    document.getElementById('profileEmail').value = profile.email || '';
    document.getElementById('profileUsername').value = profile.username || '';
    document.getElementById('profileFullName').value = profile.full_name || '';
    document.getElementById('profileUniversity').value = profile.university || '';
    document.getElementById('profilePhone').value = profile.phone || '';
    
    // Display profile picture
    const preview = document.getElementById('profilePicturePreview');
    const placeholder = document.getElementById('profilePicturePlaceholder');
    
    if (profile.profile_picture) {
        preview.src = getImageUrl(profile.profile_picture);
        preview.style.display = 'block';
        placeholder.style.display = 'none';
    } else {
        preview.style.display = 'none';
        placeholder.style.display = 'flex';
        placeholder.textContent = (profile.full_name || profile.username || 'U').charAt(0).toUpperCase();
    }
    
    // Check for pending university change
    checkPendingUniversityChange();
    
    // Load documentation preferences
    loadDocumentationPreferences();
}

async function loadDocumentationPreferences() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/documentation-preferences`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const prefs = await response.json();
            
            // Populate the form fields
            const countryField = document.getElementById('documentationCountry');
            const intakeField = document.getElementById('documentationIntake');
            const yearField = document.getElementById('documentationYear');
            
            if (countryField && prefs.country) {
                countryField.value = prefs.country;
            }
            if (intakeField && prefs.intake) {
                intakeField.value = prefs.intake;
            }
            if (yearField && prefs.year) {
                yearField.value = prefs.year;
            }
        }
    } catch (error) {
        console.error('Error loading documentation preferences:', error);
        // Fall back to localStorage
        const localPrefs = localStorage.getItem('documentationPreferences');
        if (localPrefs) {
            const prefs = JSON.parse(localPrefs);
            const intakeField = document.getElementById('documentationIntake');
            const yearField = document.getElementById('documentationYear');
            if (intakeField && prefs.intake) intakeField.value = prefs.intake;
            if (yearField && prefs.year) yearField.value = prefs.year;
        }
    }
}

async function loadDashboardStats() {
    if (!authToken) return;
    
    try {
        // Load profile completion and pending documents (main dashboard content)
        await loadProfileCompletion();
    } catch (error) {
        console.error('Load dashboard stats error:', error);
    }
}

async function loadProfileCompletion() {
    if (!authToken) return;
    
    try {
        // Load profile data
        const profileResponse = await fetch(`${API_BASE}/api/profile/`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        // Load documents
        const documentsResponse = await fetch(`${API_BASE}/api/documents/my-documents`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        let profile = null;
        let documents = [];
        
        if (profileResponse.ok) {
            profile = await profileResponse.json();
        }
        
        if (documentsResponse.ok) {
            documents = await documentsResponse.json();
        }
        
        // Calculate profile completion
        const completionData = calculateProfileCompletion(profile, documents);
        
        // Update UI
        updateProfileCompletionUI(completionData);
        
        // Update visa journey tracker
        updateVisaJourneyUI(documents);
        updateOverviewDocumentHealthUI(documents);
        
        // NOTE: We no longer save to R2 on every dashboard load
        // R2 is only updated when data actually changes (document upload/delete, profile update, preferences update)
    } catch (error) {
        console.error('Load profile completion error:', error);
    }
}

function updateOverviewDocumentHealthUI(documents) {
    const totalUploaded = documents.length;
    const uniqueTypes = new Set(documents.map(doc => doc.document_type).filter(Boolean)).size;
    const validatedCount = documents.filter(doc => doc.is_valid === true).length;
    const needsReviewCount = documents.filter(doc => doc.is_valid === false).length;
    const pendingValidationCount = documents.filter(doc => doc.is_valid === null || doc.is_valid === undefined).length;
    const processedCount = documents.filter(doc => doc.is_processed === true).length;

    const reviewedCount = validatedCount + needsReviewCount;
    const validationRate = reviewedCount > 0 ? Math.round((validatedCount / reviewedCount) * 100) : 0;
    const processingRate = totalUploaded > 0 ? Math.round((processedCount / totalUploaded) * 100) : 0;
    const healthScore = totalUploaded > 0 ? Math.round((validationRate * 0.7) + (processingRate * 0.3)) : 0;

    setTextContent('overviewTotalUploaded', totalUploaded);
    setTextContent('overviewUniqueTypes', uniqueTypes);
    setTextContent('overviewValidatedCount', validatedCount);
    setTextContent('overviewNeedsReviewCount', needsReviewCount);
    setTextContent('overviewPendingValidationCount', pendingValidationCount);
    setTextContent('overviewProcessedCount', processedCount);
    setTextContent('overviewValidationRate', `${validationRate}%`);

    const rateBar = document.getElementById('overviewValidationRateBar');
    if (rateBar) {
        rateBar.style.width = `${validationRate}%`;
    }

    const healthBadge = document.getElementById('overviewDocumentHealthStatus');
    if (healthBadge) {
        if (totalUploaded === 0) {
            healthBadge.textContent = 'No Data';
            healthBadge.style.background = 'var(--bg-tertiary)';
            healthBadge.style.borderColor = 'var(--border-color)';
            healthBadge.style.color = 'var(--text-primary)';
        } else if (needsReviewCount === 0 && healthScore >= 85) {
            healthBadge.textContent = 'Excellent';
            healthBadge.style.background = 'rgba(16, 185, 129, 0.15)';
            healthBadge.style.borderColor = 'rgba(16, 185, 129, 0.35)';
            healthBadge.style.color = '#34d399';
        } else if (healthScore >= 70) {
            healthBadge.textContent = 'Good';
            healthBadge.style.background = 'rgba(99, 102, 241, 0.15)';
            healthBadge.style.borderColor = 'rgba(99, 102, 241, 0.35)';
            healthBadge.style.color = '#818cf8';
        } else if (healthScore >= 50) {
            healthBadge.textContent = 'Fair';
            healthBadge.style.background = 'rgba(245, 158, 11, 0.15)';
            healthBadge.style.borderColor = 'rgba(245, 158, 11, 0.35)';
            healthBadge.style.color = '#fbbf24';
        } else {
            healthBadge.textContent = 'Needs Attention';
            healthBadge.style.background = 'rgba(239, 68, 68, 0.15)';
            healthBadge.style.borderColor = 'rgba(239, 68, 68, 0.35)';
            healthBadge.style.color = '#f87171';
        }
    }

    const listContainer = document.getElementById('overviewValidationList');
    if (listContainer) {
        if (totalUploaded === 0) {
            listContainer.innerHTML = '<div class="overview-health-empty">No documents uploaded yet.</div>';
            return;
        }

        const recentDocuments = [...documents]
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .slice(0, 5);

        listContainer.innerHTML = recentDocuments.map((doc) => {
            let statusLabel = 'Pending';
            let statusStyle = 'background: rgba(148, 163, 184, 0.18); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3);';

            if (doc.is_valid === true) {
                statusLabel = 'Valid';
                statusStyle = 'background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35);';
            } else if (doc.is_valid === false) {
                statusLabel = 'Needs Review';
                statusStyle = 'background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35);';
            }

            const name = doc.document_type ? formatDocumentType(doc.document_type) : (doc.original_filename || 'Document');
            const encodedDocumentType = encodeURIComponent(doc.document_type || '');
            const documentId = Number.isFinite(doc.id) ? doc.id : 0;

            return `
                <div class="overview-health-item overview-health-item-clickable" onclick="jumpToDocumentInDocumentsTab(${documentId}, '${encodedDocumentType}')" title="Open in Documents tab">
                    <div class="overview-health-item-name">${escapeHtml(name)}</div>
                    <div class="overview-health-item-status" style="${statusStyle}">${statusLabel}</div>
                </div>
            `;
        }).join('');
    }
}

function setTextContent(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = String(value);
    }
}

function formatDocumentType(type) {
    return type
        .replace(/[-_]/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

async function jumpToDocumentInDocumentsTab(documentId, encodedDocumentType = '') {
    const documentType = encodedDocumentType ? decodeURIComponent(encodedDocumentType) : '';

    switchDashboardTab('documents');

    // Ensure document list is freshly rendered before searching for anchors.
    await loadMyDocuments();

    const targetById = documentId ? document.querySelector(`[data-document-id="${documentId}"]`) : null;
    const targetByType = !targetById && documentType
        ? document.querySelector(`[data-document-type="${documentType}"]`)
        : null;
    const target = targetById || targetByType;

    if (!target) {
        showMessage('Could not find that document in the documents list.', 'error');
        return;
    }

    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('document-focus-highlight');
    setTimeout(() => target.classList.remove('document-focus-highlight'), 2200);
}

async function saveVisaStatusToR2() {
    if (!authToken) return;
    
    try {
        // Use POST /refresh endpoint to actually write to R2
        // GET /visa-status only reads (doesn't write)
        const response = await fetch(`${API_BASE}/api/documents/visa-status/refresh`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log('Visa status saved to R2:', data.r2_key);
        }
    } catch (error) {
        console.error('Failed to save visa status to R2:', error);
    }
}

function calculateProfileCompletion(profile, documents) {
    // Profile fields to check
    const profileFields = {
        'full_name': profile?.full_name,
        'university': profile?.university,
        'phone': profile?.phone,
        'profile_picture': profile?.profile_picture
    };
    
    // Required documents list (based on common visa requirements)
    const requiredDocuments = [
        'passport',
        'ds-160-confirmation',
        'ds-160-application',
        'us-visa-appointment-letter',
        'visa-fee-receipt',
        'photograph-2x2',
        'form-i20-signed',
        'university-admission-letter',
        'bank-balance-certificate',
        'transcripts-marksheets',
        'degree-certificates',
        'i901-sevis-fee-confirmation'
    ];
    
    // Count completed profile fields
    let completedFields = 0;
    const totalFields = Object.keys(profileFields).length;
    
    for (const field of Object.values(profileFields)) {
        if (field && field.trim() !== '') {
            completedFields++;
        }
    }
    
    // Get uploaded document types
    const uploadedDocTypes = new Set(
        documents.map(doc => doc.document_type).filter(type => type)
    );
    
    // Find pending documents
    const pendingDocuments = requiredDocuments.filter(docType => !uploadedDocTypes.has(docType));
    
    // Calculate completion percentage
    // Profile fields: 40% weight, Documents: 60% weight
    const profileCompletion = (completedFields / totalFields) * 100;
    const documentsCompletion = ((requiredDocuments.length - pendingDocuments.length) / requiredDocuments.length) * 100;
    const overallCompletion = Math.round((profileCompletion * 0.4) + (documentsCompletion * 0.6));
    
    return {
        overallCompletion,
        profileCompletion: Math.round(profileCompletion),
        documentsCompletion: Math.round(documentsCompletion),
        pendingDocuments,
        uploadedCount: documents.length,
        totalRequiredDocuments: requiredDocuments.length
    };
}

function updateProfileCompletionUI(data) {
    // Update completion percentage
    const percentEl = document.getElementById('profileCompletionPercent');
    const barEl = document.getElementById('profileCompletionBar');
    const pendingListEl = document.getElementById('pendingDocumentsList');
    
    if (percentEl) {
        percentEl.textContent = `${data.overallCompletion}%`;
    }
    
    if (barEl) {
        barEl.style.width = `${data.overallCompletion}%`;
    }
    
    // Update pending documents list
    if (pendingListEl) {
        if (data.pendingDocuments.length === 0) {
            pendingListEl.innerHTML = `
                <div style="background: #d4edda; border: 1px solid #c3e6cb; border-radius: 0.5rem; padding: 0.75rem; text-align: center;">
                    <span style="color: #155724; font-weight: 600;">✓ All required documents uploaded!</span>
                </div>
            `;
        } else {
            // Map document type values to display names
            const docTypeNames = {
                'passport': 'Passport',
                'ds-160-confirmation': 'DS-160 Confirmation Page',
                'ds-160-application': 'DS-160 Application',
                'us-visa-appointment-letter': 'US Visa Appointment Letter',
                'visa-fee-receipt': 'Visa Fee Receipt',
                'photograph-2x2': 'Photograph (2x2 Inches)',
                'form-i20-signed': 'Form I-20 (Signed)',
                'university-admission-letter': 'University Admission Letter',
                'bank-balance-certificate': 'Bank balance certificate',
                'transcripts-marksheets': 'Transcripts / mark sheets',
                'degree-certificates': 'Degree certificates',
                'i901-sevis-fee-confirmation': 'I-901 SEVIS fee payment confirmation'
            };
            
            const pendingList = data.pendingDocuments.slice(0, 5).map(docType => {
                const displayName = docTypeNames[docType] || docType;
                return `
                    <div style="display: flex; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border-color);">
                        <span style="color: var(--danger-color); margin-right: 0.5rem;">○</span>
                        <span style="color: var(--text-primary); font-size: 0.875rem;">${escapeHtml(displayName)}</span>
                    </div>
                `;
            }).join('');
            
            const moreCount = data.pendingDocuments.length > 5 ? data.pendingDocuments.length - 5 : 0;
            
            pendingListEl.innerHTML = `
                ${pendingList}
                ${moreCount > 0 ? `
                    <div style="padding: 0.5rem 0; text-align: center; color: var(--text-secondary); font-size: 0.875rem;">
                        +${moreCount} more document${moreCount > 1 ? 's' : ''} pending
                    </div>
                ` : ''}
                <div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border-color); font-size: 0.875rem; color: var(--text-secondary);">
                    ${data.uploadedCount} of ${data.totalRequiredDocuments} required documents uploaded
                </div>
            `;
        }
    }
}

// Visa Journey Tracker Functions
function calculateVisaJourneyStage(documents) {
    // Get uploaded document types
    const uploadedDocTypes = new Set(
        documents.map(doc => doc.document_type).filter(type => type)
    );
    
    // Define stages and their required documents
    const stages = [
        {
            stage: 1,
            name: 'Getting Started',
            emoji: '📝',
            description: 'Welcome! Start your F1 visa journey.',
            nextStep: 'Upload your university offer/admission letter',
            requiredDocs: []
        },
        {
            stage: 2,
            name: 'Admission Received',
            emoji: '🎓',
            description: 'University admission confirmed!',
            nextStep: 'Upload your passport and academic documents',
            requiredDocs: ['university-admission-letter']
        },
        {
            stage: 3,
            name: 'Documents Ready',
            emoji: '📄',
            description: 'Essential documents collected.',
            nextStep: 'Get your signed I-20 from your university',
            requiredDocs: ['passport', 'degree-certificates', 'transcripts-marksheets']
        },
        {
            stage: 4,
            name: 'I-20 Received',
            emoji: '📘',
            description: 'Great! You have your I-20 from the university.',
            nextStep: 'Complete your DS-160 application online',
            requiredDocs: ['form-i20-signed']
        },
        {
            stage: 5,
            name: 'DS-160 Filed',
            emoji: '📋',
            description: 'DS-160 application submitted successfully.',
            nextStep: 'Pay your SEVIS I-901 fee and visa fee',
            requiredDocs: ['ds-160-confirmation']
        },
        {
            stage: 6,
            name: 'Fees Paid',
            emoji: '💳',
            description: 'SEVIS and visa fees payment confirmed.',
            nextStep: 'Schedule your visa interview appointment',
            requiredDocs: ['i901-sevis-fee-confirmation', 'visa-fee-receipt']
        },
        {
            stage: 7,
            name: 'Ready to Fly!',
            emoji: '✈️',
            description: 'Interview scheduled! All documents ready.',
            nextStep: 'You\'re all set! Good luck with your visa interview!',
            requiredDocs: ['us-visa-appointment-letter', 'photograph-2x2', 'bank-balance-certificate']
        }
    ];
    
    // Calculate current stage based on documents
    let currentStage = 1; // Start at stage 1
    
    // Check stage 2: University admission letter
    if (uploadedDocTypes.has('university-admission-letter')) {
        currentStage = 2;
    }
    
    // Check stage 3: Passport and academic documents
    const hasBasicDocs = uploadedDocTypes.has('passport') &&
                         (uploadedDocTypes.has('degree-certificates') || uploadedDocTypes.has('transcripts-marksheets'));
    if (currentStage >= 2 && hasBasicDocs) {
        currentStage = 3;
    }
    
    // Check stage 4: I-20
    if (currentStage >= 3 && uploadedDocTypes.has('form-i20-signed')) {
        currentStage = 4;
    }
    
    // Check stage 5: DS-160
    if (currentStage >= 4 && uploadedDocTypes.has('ds-160-confirmation')) {
        currentStage = 5;
    }
    
    // Check stage 6: SEVIS and visa fees
    if (currentStage >= 5 && uploadedDocTypes.has('i901-sevis-fee-confirmation')) {
        currentStage = 6;
    }
    
    // Check stage 7: Interview scheduled and all docs ready
    const interviewReady = uploadedDocTypes.has('us-visa-appointment-letter') &&
                           uploadedDocTypes.has('photograph-2x2') &&
                           uploadedDocTypes.has('bank-balance-certificate');
    if (currentStage >= 6 && interviewReady) {
        currentStage = 7;
    }
    
    return {
        currentStage,
        stageInfo: stages[currentStage - 1],
        stages
    };
}

function updateVisaJourneyUI(documents) {
    const journeyData = calculateVisaJourneyStage(documents);
    const { currentStage, stageInfo, stages } = journeyData;
    
    // Update progress line
    const progressLine = document.getElementById('journeyProgressLine');
    if (progressLine) {
        // Calculate progress percentage (stage 1 = 0%, stage 7 = 100%)
        const progressPercent = ((currentStage - 1) / (stages.length - 1)) * 90;
        progressLine.style.width = `${progressPercent}%`;
    }
    
    // Update stage icons
    for (let i = 1; i <= 7; i++) {
        const stageIcon = document.getElementById(`stageIcon${i}`);
        if (stageIcon) {
            if (i < currentStage) {
                // Completed stage
                stageIcon.style.background = 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))';
                stageIcon.style.color = 'white';
                stageIcon.style.boxShadow = '0 4px 12px rgba(99, 102, 241, 0.4)';
                stageIcon.innerHTML = '✓';
            } else if (i === currentStage) {
                // Current stage
                stageIcon.style.background = 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))';
                stageIcon.style.color = 'white';
                stageIcon.style.boxShadow = '0 4px 12px rgba(99, 102, 241, 0.4)';
                stageIcon.style.animation = 'pulse 2s ease-in-out infinite';
            } else {
                // Future stage
                stageIcon.style.background = 'var(--border-color)';
                stageIcon.style.color = 'var(--text-secondary)';
                stageIcon.style.boxShadow = 'none';
            }
        }
    }
    
    // Update current stage info box
    const currentStageEmoji = document.getElementById('currentStageEmoji');
    const currentStageName = document.getElementById('currentStageName');
    const currentStageDesc = document.getElementById('currentStageDesc');
    const nextStepText = document.getElementById('nextStepText');
    
    if (currentStageEmoji) currentStageEmoji.textContent = stageInfo.emoji;
    if (currentStageName) currentStageName.textContent = `Stage ${currentStage}: ${stageInfo.name}`;
    if (currentStageDesc) currentStageDesc.textContent = stageInfo.description;
    if (nextStepText) nextStepText.textContent = stageInfo.nextStep;
    
    // Hide next step hint if at final stage
    const nextStepHint = document.getElementById('nextStepHint');
    if (nextStepHint && currentStage === 7) {
        nextStepHint.innerHTML = '<span style="color: #34d399; font-weight: 600;">🎉 Congratulations! You\'re all set for your journey!</span>';
    }
}

function handleProfilePicturePreview(e) {
    const file = e.target.files[0];
    const preview = document.getElementById('profilePicturePreview');
    const placeholder = document.getElementById('profilePicturePlaceholder');
    
    if (file) {
        // Validate file type
        if (!file.type.startsWith('image/')) {
            showMessage('Please select an image file', 'error');
            e.target.value = '';
            return;
        }
        
        // Validate file size (2MB)
        if (file.size > 2 * 1024 * 1024) {
            showMessage('Image size must be less than 2MB', 'error');
            e.target.value = '';
            return;
        }
        
        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
            placeholder.style.display = 'none';
        };
        reader.readAsDataURL(file);
    }
}

async function uploadProfilePicture(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`${API_BASE}/api/upload/profile-picture`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${authToken}`
        },
        body: formData
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to upload profile picture');
    }
    
    const data = await response.json();
    return data.url;
}

async function handleUpdateProfile(e) {
    e.preventDefault();
    if (!authToken) {
        showMessage('Please login to update profile', 'error');
        return;
    }
    
    const getValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === '' ? null : value;
    };
    
    // Handle profile picture upload if a file is selected
    let profilePictureUrl = null;
    const profilePictureInput = document.getElementById('profilePictureInput');
    if (profilePictureInput && profilePictureInput.files && profilePictureInput.files.length > 0) {
        try {
            showMessage('Uploading profile picture...', 'success');
            profilePictureUrl = await uploadProfilePicture(profilePictureInput.files[0]);
            showMessage('Profile picture uploaded!', 'success');
        } catch (error) {
            showMessage(error.message || 'Failed to upload profile picture', 'error');
            return;
        }
    }
    
    const profileData = {
        full_name: getValue('profileFullName'),
        // university is not editable - derived from .edu email at registration
        phone: getValue('profilePhone'),
        profile_picture: profilePictureUrl || currentUser.profile_picture || null
    };
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(profileData)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMessage('Profile updated successfully!', 'success');
            currentUser = data;
            // Update UI to reflect changes
            const userInfoEl = document.getElementById('userInfo');
            if (currentUser.profile_picture) {
                userInfoEl.innerHTML = `<img src="${getImageUrl(currentUser.profile_picture)}" alt="${currentUser.username}"> <span>${currentUser.username}</span>`;
            } else {
                userInfoEl.innerHTML = `<div style="width: 2rem; height: 2rem; border-radius: 50%; background: rgba(255,255,255,0.3); display: flex; align-items: center; justify-content: center; font-weight: 600;">${(currentUser.full_name || currentUser.username).charAt(0).toUpperCase()}</div> <span>${currentUser.username}</span>`;
            }
            // Reload profile display if on dashboard
            displayProfile(data);
            
            // Update R2 with new profile data
            await saveVisaStatusToR2();
        } else {
            let errorMessage = 'Failed to update profile';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Update profile error:', error);
        showMessage('An error occurred. Please check your connection and try again.', 'error');
    }
}

// ========== Change University Functions ==========

function showChangeUniversityModal() {
    const modal = document.getElementById('changeUniversityModal');
    modal.style.display = 'flex';
    document.getElementById('newUniversityEmail').value = '';
    document.getElementById('newUniversityName').value = '';
    document.getElementById('universityChangeError').style.display = 'none';
    
    // Add email input listener for auto-fill
    const emailInput = document.getElementById('newUniversityEmail');
    emailInput.addEventListener('input', debounce(checkNewUniversityEmail, 500));
}

function closeChangeUniversityModal() {
    document.getElementById('changeUniversityModal').style.display = 'none';
}

// Simple debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

async function checkNewUniversityEmail() {
    const email = document.getElementById('newUniversityEmail').value.trim();
    const universityInput = document.getElementById('newUniversityName');
    const errorDiv = document.getElementById('universityChangeError');
    
    if (!email || !email.includes('@')) {
        universityInput.value = '';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/university-by-email?email=${encodeURIComponent(email)}`);
        const data = await response.json();
        
        if (data.is_valid && data.university_name) {
            universityInput.value = data.university_name;
            errorDiv.style.display = 'none';
        } else {
            universityInput.value = '';
            errorDiv.textContent = 'Please use a valid university .edu email address.';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Error checking university email:', error);
        universityInput.value = '';
    }
}

async function handleChangeUniversity(e) {
    e.preventDefault();
    
    const email = document.getElementById('newUniversityEmail').value.trim();
    const university = document.getElementById('newUniversityName').value.trim();
    const errorDiv = document.getElementById('universityChangeError');
    const submitBtn = document.getElementById('changeUniversitySubmitBtn');
    const btnText = document.getElementById('changeUniversityBtnText');
    
    if (!email || !university) {
        errorDiv.textContent = 'Please enter a valid university email.';
        errorDiv.style.display = 'block';
        return;
    }
    
    // Disable button and show loading
    submitBtn.disabled = true;
    btnText.textContent = 'Sending...';
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/request-university-change`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                new_email: email,
                new_university: university
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            closeChangeUniversityModal();
            showMessage(data.message || 'Verification email sent! Check your inbox.', 'success');
            // Show pending change UI
            checkPendingUniversityChange();
        } else {
            errorDiv.textContent = data.detail || 'Failed to request university change.';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        console.error('Change university error:', error);
        errorDiv.textContent = 'An error occurred. Please try again.';
        errorDiv.style.display = 'block';
    } finally {
        submitBtn.disabled = false;
        btnText.textContent = 'Send Verification';
    }
}

async function checkPendingUniversityChange() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/pending-university-change`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        const data = await response.json();
        const pendingDiv = document.getElementById('pendingUniversityChange');
        const pendingName = document.getElementById('pendingUniversityName');
        
        if (data.has_pending_change) {
            pendingName.textContent = data.pending_university;
            pendingDiv.style.display = 'block';
        } else {
            pendingDiv.style.display = 'none';
        }
    } catch (error) {
        console.error('Error checking pending university change:', error);
    }
}

async function cancelUniversityChange() {
    if (!authToken) return;
    
    if (!confirm('Are you sure you want to cancel the university change request?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/auth/cancel-university-change`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            showMessage('University change request cancelled.', 'success');
            document.getElementById('pendingUniversityChange').style.display = 'none';
        } else {
            const data = await response.json();
            showMessage(data.detail || 'Failed to cancel request.', 'error');
        }
    } catch (error) {
        console.error('Cancel university change error:', error);
        showMessage('An error occurred.', 'error');
    }
}

// ========== End Change University Functions ==========

async function handleDeleteAccount() {
    if (!authToken) {
        showMessage('Please login to delete your account', 'error');
        return;
    }
    
    // Double confirmation
    const confirmText = 'DELETE';
    const userInput = prompt(`This action cannot be undone. All your data including documents and profile will be permanently deleted.\n\nType "${confirmText}" to confirm account deletion:`);
    
    if (userInput !== confirmText) {
        if (userInput !== null) {
            showMessage('Account deletion cancelled. The confirmation text did not match.', 'error');
        }
        return;
    }
    
    // Final confirmation
    if (!confirm('Are you absolutely sure you want to delete your account? This action is permanent and cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/profile/`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok || response.status === 204) {
            showMessage('Your account has been deleted successfully.', 'success');
            // Clear local storage and logout
            localStorage.removeItem('authToken');
            authToken = null;
            currentUser = null;
            updateUIForAuth();
            showHomepage();
            // Redirect to home after a short delay
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to delete account');
        }
    } catch (error) {
        console.error('Delete account error:', error);
        showMessage(error.message || 'An error occurred while deleting your account. Please try again.', 'error');
    }
}

// Image Gallery Functions
let currentGalleryImages = [];
let currentGalleryIndex = 0;
let currentGalleryItemId = null;
let currentGalleryItemTitle = '';

function handleItemImageClick(element) {
    const imageKey = element.getAttribute('data-image-key');
    const itemId = element.getAttribute('data-item-id');
    const itemTitle = element.getAttribute('data-item-title');
    
    if (!imageKey || !window.itemImagesMap || !window.itemImagesMap[imageKey]) {
        return;
    }
    
    openImageGallery(itemId, itemTitle, window.itemImagesMap[imageKey]);
}

function openImageGallery(itemId, itemTitle, images) {
    try {
        currentGalleryImages = Array.isArray(images) ? images : [];
        currentGalleryItemId = itemId;
        currentGalleryItemTitle = itemTitle;
        currentGalleryIndex = 0;
        
        if (currentGalleryImages.length === 0) {
            return;
        }
        
        const modal = document.getElementById('imageGalleryModal');
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
        
        updateGalleryDisplay();
        setupGalleryKeyboardNavigation();
    } catch (error) {
        console.error('Error opening image gallery:', error);
    }
}

function closeImageGallery() {
    const modal = document.getElementById('imageGalleryModal');
    modal.style.display = 'none';
    document.body.style.overflow = ''; // Restore scrolling
    removeGalleryKeyboardNavigation();
}

function navigateGallery(direction) {
    if (currentGalleryImages.length === 0) return;
    
    currentGalleryIndex += direction;
    
    // Wrap around
    if (currentGalleryIndex < 0) {
        currentGalleryIndex = currentGalleryImages.length - 1;
    } else if (currentGalleryIndex >= currentGalleryImages.length) {
        currentGalleryIndex = 0;
    }
    
    updateGalleryDisplay();
}

function updateGalleryDisplay() {
    if (currentGalleryImages.length === 0) return;
    
    const mainImage = document.getElementById('galleryMainImage');
    const counter = document.getElementById('galleryImageCounter');
    const thumbnails = document.getElementById('galleryThumbnails');
    
    // Update main image
    mainImage.src = currentGalleryImages[currentGalleryIndex];
    mainImage.alt = `${currentGalleryItemTitle} - Image ${currentGalleryIndex + 1}`;
    
    // Update counter
    counter.textContent = `${currentGalleryIndex + 1} / ${currentGalleryImages.length}`;
    
    // Update thumbnails
    thumbnails.innerHTML = currentGalleryImages.map((img, index) => {
        const isActive = index === currentGalleryIndex ? 'active' : '';
        return `
            <div class="gallery-thumbnail ${isActive}" onclick="jumpToGalleryImage(${index})">
                <img src="${img}" alt="Thumbnail ${index + 1}">
            </div>
        `;
    }).join('');
    
    // Show/hide navigation arrows
    const prevBtn = document.querySelector('.image-gallery-prev');
    const nextBtn = document.querySelector('.image-gallery-next');
    
    if (currentGalleryImages.length <= 1) {
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
    } else {
        prevBtn.style.display = 'flex';
        nextBtn.style.display = 'flex';
    }
}

function jumpToGalleryImage(index) {
    if (index >= 0 && index < currentGalleryImages.length) {
        currentGalleryIndex = index;
        updateGalleryDisplay();
    }
}

function setupGalleryKeyboardNavigation() {
    document.addEventListener('keydown', handleGalleryKeyPress);
}

function removeGalleryKeyboardNavigation() {
    document.removeEventListener('keydown', handleGalleryKeyPress);
}

// Documentation Agent functions
function initializeYearDropdown() {
    const yearSelect = document.getElementById('documentationYear');
    if (!yearSelect) return;
    
    // Clear existing options except the first one
    yearSelect.innerHTML = '<option value="">Select Year</option>';
    
    // Get current year
    const currentYear = new Date().getFullYear();
    
    // Add years from current year to 5 years in the future
    for (let i = 0; i <= 5; i++) {
        const year = currentYear + i;
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        yearSelect.appendChild(option);
    }
}

function loadDocumentationPreferences() {
    // Load saved preferences from localStorage
    const savedPreferences = localStorage.getItem('documentationPreferences');
    if (savedPreferences) {
        try {
            const prefs = JSON.parse(savedPreferences);
            const intakeSelect = document.getElementById('documentationIntake');
            const yearSelect = document.getElementById('documentationYear');
            
            if (intakeSelect && prefs.intake) {
                intakeSelect.value = prefs.intake;
            }
            if (yearSelect && prefs.year) {
                yearSelect.value = prefs.year;
            }
        } catch (error) {
            console.error('Error loading documentation preferences:', error);
        }
    }
}

async function handleDocumentationForm(e) {
    e.preventDefault();
    
    const intake = document.getElementById('documentationIntake').value;
    const year = document.getElementById('documentationYear').value;
    const country = document.getElementById('documentationCountry').value;
    
    if (!intake || !year) {
        showMessage('Please select both intake and year', 'error');
        return;
    }
    
    if (!authToken) {
        showMessage('Please login to save preferences', 'error');
        return;
    }
    
    try {
        // Save to backend API
        const response = await fetch(`${API_BASE}/api/profile/documentation-preferences`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                country: country,
                intake: intake,
                year: parseInt(year)
            })
        });
        
        if (response.ok) {
            // Also save to localStorage as backup
            const preferences = {
                country: country,
                intake: intake,
                year: year,
                savedAt: new Date().toISOString()
            };
            localStorage.setItem('documentationPreferences', JSON.stringify(preferences));
            
            showMessage(`Preferences saved: ${intake} ${year}`, 'success');
            
            // Refresh the R2 student profile file
            await saveVisaStatusToR2();
        } else {
            const data = await response.json();
            showMessage(data.detail || 'Failed to save preferences', 'error');
        }
    } catch (error) {
        console.error('Save preferences error:', error);
        showMessage('Failed to save preferences. Please try again.', 'error');
    }
}

async function handleDocumentUpload(e) {
    e.preventDefault();
    if (!authToken) {
        showMessage('Please login to upload documents', 'error');
        return;
    }
    
    const fileInput = document.getElementById('documentFile');
    const password = document.getElementById('documentPassword').value;
    const documentType = document.getElementById('documentType').value;
    const description = document.getElementById('documentDescription').value.trim();
    const country = document.getElementById('documentationCountry').value;
    const intake = document.getElementById('documentationIntake').value;
    const year = document.getElementById('documentationYear').value ? parseInt(document.getElementById('documentationYear').value) : null;
    
    if (!fileInput.files || fileInput.files.length === 0) {
        showMessage('Please select a file to upload', 'error');
        return;
    }
    
    if (!password) {
        showMessage('Please enter your password to encrypt the document', 'error');
        return;
    }
    
    if (!documentType) {
        showMessage('Please select a document type', 'error');
        return;
    }
    
    const file = fileInput.files[0];
    
    // Validate file size (50MB)
    const maxSize = 50 * 1024 * 1024;
    if (file.size > maxSize) {
        showMessage('File is too large. Maximum size is 50MB', 'error');
        return;
    }
    
    try {
        showMessage('Encrypting and uploading document...', 'success');
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('password', password);  // Required for Zero-Knowledge encryption
        formData.append('document_type', documentType);  // Required field
        if (country) formData.append('country', country);
        if (intake) formData.append('intake', intake);
        if (year) formData.append('year', year);
        if (description) formData.append('description', description);
        
        const response = await fetch(`${API_BASE}/api/documents/upload`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            },
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok) {
            const documentName = file.name;
            const docType = documentType;
            
            // Check for validation results
            if (data.validation) {
                const validation = data.validation;
                if (!validation.is_valid) {
                    // Document validation failed
                    const docTypeText = docType ? ` (${docType})` : '';
                    const notificationMessage = `File: ${documentName}${docTypeText}\n\n${validation.message || 'The uploaded document does not match the specified type. Please verify and upload the correct document.'}`;
                    
                    addNotification(
                        'Rilono AI: Document Validation Failed',
                        notificationMessage,
                        'error',
                        validation.details
                    );
                    showMessage(validation.message || 'Document uploaded but validation failed. Please check notifications.', 'error');
                } else {
                    // Document validation passed
                    const name = validation.details?.Name || '';
                    const docTypeText = docType ? ` (${docType})` : '';
                    const successMsg = `File: ${documentName}${docTypeText}\n\n${name ? `Extracted name: ${name}\n\n` : ''}Document validated successfully! All information has been extracted.`;
                    
                    addNotification(
                        'Rilono AI: Document Validated',
                        successMsg,
                        'success',
                        validation.details
                    );
                    showMessage('Document encrypted and uploaded successfully!', 'success');
                }
            } else {
                // No validation data (legacy or processing failed)
                const docTypeText = docType ? ` (${docType})` : '';
                addNotification(
                    'Rilono AI: Document Uploaded',
                    `File: ${documentName}${docTypeText}\n\nDocument uploaded successfully. Processing may be in progress.`,
                    'info',
                    null
                );
                showMessage('Document encrypted and uploaded successfully!', 'success');
            }
            
            document.getElementById('documentUploadForm').reset();
            // Also reset the searchable dropdown
            document.getElementById('documentType').value = '';
            document.getElementById('documentTypeSearch').value = '';
            const dropdownItems = document.querySelectorAll('#documentTypeList .dropdown-item');
            dropdownItems.forEach(item => item.classList.remove('selected'));
            await loadMyDocuments();
            
            // Refresh visa status after document upload
            await saveVisaStatusToR2();
            await loadDashboardStats(); // Refresh the journey tracker
        } else {
            let errorMessage = 'Failed to upload document';
            if (data.detail) {
                if (Array.isArray(data.detail)) {
                    errorMessage = data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ');
                } else {
                    errorMessage = data.detail;
                }
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Document upload error:', error);
        showMessage('An error occurred while uploading the document. Please try again.', 'error');
    }
}

async function loadMyDocuments() {
    if (!authToken) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/documents/my-documents`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const documents = await response.json();
            displayDocuments(documents);
        } else {
            const error = await response.json().catch(() => ({}));
            if (response.status === 401) {
                showMessage('Session expired. Please login again.', 'error');
                logout();
            } else {
                console.error('Failed to load documents:', error);
            }
        }
    } catch (error) {
        console.error('Load documents error:', error);
    }
}

function getDocumentValidationMeta(doc) {
    if (doc.is_valid === true) {
        return {
            statusLabel: 'Valid',
            statusStyle: 'background: rgba(16, 185, 129, 0.15); color: #166534; border: 1px solid rgba(22, 101, 52, 0.25);',
            cardStyle: 'border: 1px solid #c3e6cb; background: #d4edda;',
            indicatorIcon: '✓',
            indicatorColor: '#28a745',
            reason: ''
        };
    }

    if (doc.is_valid === false) {
        return {
            statusLabel: 'Invalid',
            statusStyle: 'background: rgba(239, 68, 68, 0.15); color: #991b1b; border: 1px solid rgba(153, 27, 27, 0.25);',
            cardStyle: 'border: 1px solid #f5c6cb; background: #f8d7da;',
            indicatorIcon: '!',
            indicatorColor: '#dc3545',
            reason: doc.validation_message || 'Validation failed. Please upload the correct document.'
        };
    }

    const isProcessing = doc.is_processed === false;
    return {
        statusLabel: isProcessing ? 'Processing' : 'Pending Validation',
        statusStyle: 'background: rgba(245, 158, 11, 0.15); color: #92400e; border: 1px solid rgba(146, 64, 14, 0.25);',
        cardStyle: 'border: 1px solid #ffe0a3; background: #fff7e6;',
        indicatorIcon: '•',
        indicatorColor: '#d97706',
        reason: ''
    };
}

function displayDocuments(documents) {
    const container = document.getElementById('documentsContainer');
    
    // Required documents list (same as in profile completion)
    const requiredDocuments = [
        { value: 'passport', label: 'Passport' },
        { value: 'ds-160-confirmation', label: 'DS-160 Confirmation Page' },
        { value: 'ds-160-application', label: 'DS-160 Application' },
        { value: 'us-visa-appointment-letter', label: 'US Visa Appointment Letter' },
        { value: 'visa-fee-receipt', label: 'Visa Fee Receipt' },
        { value: 'photograph-2x2', label: 'Photograph (2x2 Inches)' },
        { value: 'form-i20-signed', label: 'Form I-20 (Signed)' },
        { value: 'university-admission-letter', label: 'University Admission Letter' },
        { value: 'bank-balance-certificate', label: 'Bank balance certificate' },
        { value: 'transcripts-marksheets', label: 'Transcripts / mark sheets' },
        { value: 'degree-certificates', label: 'Degree certificates' },
        { value: 'i901-sevis-fee-confirmation', label: 'I-901 SEVIS fee payment confirmation' }
    ];
    
    // Get uploaded document types
    const uploadedDocTypes = new Set(
        documents.map(doc => doc.document_type).filter(type => type)
    );
    
    // Separate uploaded and pending documents
    const uploadedDocs = documents.filter(doc => doc.document_type && requiredDocuments.some(req => req.value === doc.document_type));
    const otherDocs = documents.filter(doc => !doc.document_type || !requiredDocuments.some(req => req.value === doc.document_type));
    const pendingDocs = requiredDocuments.filter(req => !uploadedDocTypes.has(req.value));
    
    let html = '';
    
    // Show uploaded required documents with checkmarks
    if (uploadedDocs.length > 0 || pendingDocs.length > 0) {
        html += '<div style="margin-bottom: 2rem;">';
        html += '<h4 style="font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: var(--text-primary);">Required Documents</h4>';
        
        // Show uploaded documents
        uploadedDocs.forEach(doc => {
            const fileSizeMB = (doc.file_size / (1024 * 1024)).toFixed(2);
            const uploadDate = new Date(doc.created_at).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
            const isEncrypted = doc.encrypted_file_key || !doc.file_url;
            const docTypeLabel = requiredDocuments.find(req => req.value === doc.document_type)?.label || doc.document_type;
            const validationMeta = getDocumentValidationMeta(doc);
            
            html += `
                <div data-document-id="${doc.id}" data-document-type="${escapeHtml(doc.document_type || '')}" style="${validationMeta.cardStyle} border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem;">
                    <div style="display: flex; align-items: start; gap: 0.75rem;">
                        <div style="color: ${validationMeta.indicatorColor}; font-size: 1.25rem; font-weight: bold; flex-shrink: 0;">${validationMeta.indicatorIcon}</div>
                        <div style="flex: 1;">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; margin-bottom: 0.25rem; color: #1f2937;">
                                        ${escapeHtml(docTypeLabel)}
                                    </div>
                                    <div style="font-size: 0.875rem; color: var(--text-secondary);">
                                        ${escapeHtml(doc.original_filename)} • ${fileSizeMB} MB • ${uploadDate}
                                        ${isEncrypted ? ' • <span style="color: #28a745;">🔒 Encrypted</span>' : ''}
                                    </div>
                                    <div style="margin-top: 0.5rem; display: flex; align-items: center; gap: 0.5rem;">
                                        <span style="font-size: 0.8rem; color: var(--text-secondary);">Validation:</span>
                                        <span style="font-size: 0.78rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${validationMeta.statusStyle}">
                                            ${validationMeta.statusLabel}
                                        </span>
                                    </div>
                                    ${validationMeta.reason ? `
                                        <div style="font-size: 0.85rem; margin-top: 0.5rem; color: #991b1b;">
                                            <strong>Reason:</strong> ${escapeHtml(validationMeta.reason)}
                                        </div>
                                    ` : ''}
                                    ${doc.description ? `<div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem; font-style: italic;">${escapeHtml(doc.description)}</div>` : ''}
                                </div>
                            </div>
                            <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                                ${isEncrypted ? `
                                    <button onclick="downloadEncryptedDocument(${doc.id})" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem;">Download</button>
                                ` : `
                                    <a href="${doc.file_url}" target="_blank" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem; text-decoration: none; display: inline-block;">View</a>
                                    <a href="${API_BASE}/api/documents/${doc.id}/download" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: var(--bg-color); border: 1px solid var(--border-color); text-decoration: none; display: inline-block;">Download</a>
                                `}
                                <button onclick="deleteDocument(${doc.id}, '${escapeHtml(doc.original_filename)}')" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: var(--danger-color); color: white; border: none;">Delete</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        
        // Show pending documents with crosses
        pendingDocs.forEach(pendingDoc => {
            html += `
                <div data-document-type="${escapeHtml(pendingDoc.value)}" style="border: 1px solid #f5c6cb; border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem; background: #f8d7da;">
                    <div style="display: flex; align-items: center; gap: 0.75rem;">
                        <div style="color: #dc3545; font-size: 1.25rem; font-weight: bold; flex-shrink: 0;">✗</div>
                        <div style="flex: 1;">
                            <div style="font-weight: 600; color: #721c24; margin-bottom: 0.25rem;">
                                ${escapeHtml(pendingDoc.label)}
                            </div>
                            <div style="font-size: 0.875rem; color: #856404;">
                                Pending upload
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
    }
    
    // Show other uploaded documents (non-required)
    if (otherDocs.length > 0) {
        html += '<div style="margin-top: 2rem; padding-top: 2rem; border-top: 2px solid var(--border-color);">';
        html += '<h4 style="font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: var(--text-primary);">Other Documents</h4>';
        
        html += otherDocs.map(doc => {
            const fileSizeMB = (doc.file_size / (1024 * 1024)).toFixed(2);
            const uploadDate = new Date(doc.created_at).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
            const isEncrypted = doc.encrypted_file_key || !doc.file_url;
            const validationMeta = getDocumentValidationMeta(doc);
            
            return `
                <div data-document-id="${doc.id}" data-document-type="${escapeHtml(doc.document_type || '')}" style="${validationMeta.cardStyle} border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem;">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
                        <div style="flex: 1;">
                            <div style="font-weight: 600; margin-bottom: 0.25rem; color: #1f2937;">
                                ${escapeHtml(doc.original_filename)}
                                ${isEncrypted ? '<span style="font-size: 0.75rem; color: #28a745; margin-left: 0.5rem;">🔒 Encrypted</span>' : ''}
                            </div>
                            <div style="font-size: 0.875rem; color: var(--text-secondary);">
                                ${doc.document_type ? `<span style="text-transform: capitalize;">${escapeHtml(doc.document_type)}</span> • ` : ''}
                                ${fileSizeMB} MB • ${uploadDate}
                            </div>
                            <div style="margin-top: 0.5rem; display: flex; align-items: center; gap: 0.5rem;">
                                <span style="font-size: 0.8rem; color: var(--text-secondary);">Validation:</span>
                                <span style="font-size: 0.78rem; font-weight: 700; border-radius: 999px; padding: 0.15rem 0.5rem; ${validationMeta.statusStyle}">
                                    ${validationMeta.statusLabel}
                                </span>
                            </div>
                            ${validationMeta.reason ? `
                                <div style="font-size: 0.85rem; margin-top: 0.5rem; color: #991b1b;">
                                    <strong>Reason:</strong> ${escapeHtml(validationMeta.reason)}
                                </div>
                            ` : ''}
                            ${doc.description ? `<div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem; font-style: italic;">${escapeHtml(doc.description)}</div>` : ''}
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                        ${isEncrypted ? `
                            <button onclick="downloadEncryptedDocument(${doc.id})" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem;">Download</button>
                        ` : `
                            <a href="${doc.file_url}" target="_blank" class="btn btn-primary" style="font-size: 0.875rem; padding: 0.5rem 1rem; text-decoration: none; display: inline-block;">View</a>
                            <a href="${API_BASE}/api/documents/${doc.id}/download" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: var(--bg-color); border: 1px solid var(--border-color); text-decoration: none; display: inline-block;">Download</a>
                        `}
                        <button onclick="deleteDocument(${doc.id}, '${escapeHtml(doc.original_filename)}')" class="btn" style="font-size: 0.875rem; padding: 0.5rem 1rem; background: var(--danger-color); color: white; border: none;">Delete</button>
                    </div>
                </div>
            `;
        }).join('');
        
        html += '</div>';
    }
    
    // Show message if no documents at all
    if (documents.length === 0 && pendingDocs.length === 0) {
        html = '<p style="color: var(--text-secondary); text-align: center; padding: 1rem;">No documents uploaded yet</p>';
    } else if (documents.length === 0) {
        html = '<p style="color: var(--text-secondary); text-align: center; padding: 1rem;">No documents uploaded yet. Please upload the required documents above.</p>';
    }
    
    container.innerHTML = html;
}

async function downloadEncryptedDocument(documentId) {
    if (!authToken) {
        showMessage('Please login to download documents', 'error');
        return;
    }
    
    const password = prompt('Enter your password to decrypt and download this document:');
    if (!password) {
        return; // User cancelled
    }
    
    try {
        showMessage('Decrypting document...', 'success');
        
        const formData = new FormData();
        formData.append('password', password);
        
        const response = await fetch(`${API_BASE}/api/documents/${documentId}/download`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            },
            body: formData
        });
        
        if (response.ok) {
            // Get the file blob
            const blob = await response.blob();
            
            // Get filename from response headers or use default
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'document';
            if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
                if (filenameMatch) {
                    filename = filenameMatch[1];
                }
            }
            
            // Create download link
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            showMessage('Document decrypted and downloaded successfully!', 'success');
        } else {
            const error = await response.json().catch(() => ({}));
            let errorMessage = 'Failed to download document';
            if (error.detail) {
                errorMessage = error.detail;
            }
            showMessage(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Download error:', error);
        showMessage('An error occurred while downloading the document. Please try again.', 'error');
    }
}

async function deleteDocument(documentId, filename) {
    if (!authToken) {
        showMessage('Please login to delete documents', 'error');
        return;
    }
    
    // Confirm deletion
    const confirmed = confirm(`Are you sure you want to delete "${filename}"?\n\nThis action cannot be undone. The file will be permanently deleted from R2 storage.`);
    if (!confirmed) {
        return; // User cancelled
    }
    
    try {
        showMessage('Deleting document...', 'success');
        
        const response = await fetch(`${API_BASE}/api/documents/${documentId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok || response.status === 204) {
            showMessage('Document deleted successfully', 'success');
            // Reload documents list
            await loadMyDocuments();
            
            // Refresh visa status after document deletion
            await saveVisaStatusToR2();
            await loadDashboardStats();
        } else {
            const error = await response.json().catch(() => ({}));
            if (response.status === 403) {
                showMessage('You do not have permission to delete this document', 'error');
            } else if (response.status === 404) {
                showMessage('Document not found', 'error');
                // Reload documents list anyway
                await loadMyDocuments();
            } else {
                showMessage(error.detail || 'Failed to delete document. Please try again.', 'error');
            }
        }
    } catch (error) {
        console.error('Delete error:', error);
        showMessage('Failed to delete document. Please try again.', 'error');
    }
}

// Rilono AI Chat Functions
function getMainChatContainers() {
    const containers = document.querySelectorAll('.rilono-ai-messages[data-main-chat="true"]');
    if (containers.length > 0) {
        return Array.from(containers);
    }
    const fallback = document.getElementById('rilonoAiChatMessages');
    return fallback ? [fallback] : [];
}

function getMainChatForms() {
    const forms = document.querySelectorAll('.rilono-ai-form[data-main-chat-form="true"]');
    if (forms.length > 0) {
        return Array.from(forms);
    }
    const fallback = document.getElementById('rilonoAiChatForm');
    return fallback ? [fallback] : [];
}

function getMainChatWelcomeMarkup() {
    return `
        <div class="rilono-ai-message assistant">
            <div class="message-avatar">🤖</div>
            <div class="message-bubble">
                <p>Hello! I can help with your visa docs, profile status, and next steps.</p>
            </div>
        </div>
    `;
}

function handleRilonoAiChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        const form = event.target.closest('form');
        if (form) {
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }
    }
}

function autoResizeRilonoAiInput(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function sendQuickMessage(message, triggerElement = null) {
    let input = null;
    let form = null;

    if (triggerElement) {
        const chatWidget = triggerElement.closest('.rilono-ai-widget');
        if (chatWidget) {
            input = chatWidget.querySelector('.rilono-ai-input');
            form = chatWidget.querySelector('.rilono-ai-form');
        }
    }

    if (!input || !form) {
        const forms = getMainChatForms();
        if (forms.length > 0) {
            form = forms[0];
            input = form.querySelector('.rilono-ai-input');
        }
    }

    if (!input || !form) {
        return;
    }

    input.value = message;
    autoResizeRilonoAiInput(input);
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
}

function addMessageToRilonoAiChat(message, isUser = false) {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        const messageDiv = document.createElement('div');
        messageDiv.className = `rilono-ai-message ${isUser ? 'user' : 'assistant'}`;

        if (isUser) {
            messageDiv.innerHTML = `
                <div class="message-avatar">${currentUser?.full_name?.charAt(0) || currentUser?.username?.charAt(0) || 'U'}</div>
                <div class="message-bubble">
                    <p>${escapeHtml(message)}</p>
                </div>
            `;
        } else {
            // Use markdown parser for AI responses
            messageDiv.innerHTML = `
                <div class="message-avatar">🤖</div>
                <div class="message-bubble">
                    <div class="ai-response-content">${markdownToHtml(message)}</div>
                </div>
            `;
        }

        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}

function showRilonoAiTypingIndicator() {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        const existing = messagesContainer.querySelector('.rilono-ai-typing-indicator');
        if (existing) existing.remove();

        const typingDiv = document.createElement('div');
        typingDiv.className = 'rilono-ai-typing rilono-ai-typing-indicator';
        typingDiv.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="typing-bubble">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
        messagesContainer.appendChild(typingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}

function removeRilonoAiTypingIndicator() {
    document.querySelectorAll('.rilono-ai-typing-indicator').forEach((typingIndicator) => {
        typingIndicator.remove();
    });
}

// Store conversation history for Rilono AI
let rilonoAiConversationHistory = [];

async function handleRilonoAiChatSubmit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const input = form ? form.querySelector('.rilono-ai-input') : null;
    if (!input) return;
    const message = input.value.trim();
    
    if (!message) return;
    
    if (!authToken) {
        showMessage('Please login to chat with Rilono AI', 'error');
        return;
    }
    
    // Add user message to both chats
    addMessageToRilonoAiChat(message, true);
    addMessageToFloatingChat(message, true);
    
    // Add to shared conversation history
    rilonoAiConversationHistory.push({
        role: 'user',
        content: message
    });
    
    input.value = '';
    autoResizeRilonoAiInput(input);
    
    // Show typing indicator
    showRilonoAiTypingIndicator();
    
    try {
        // Call the AI chat API
        const response = await fetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: message,
                conversation_history: rilonoAiConversationHistory.slice(-10)  // Last 10 messages for context
            })
        });
        
        removeRilonoAiTypingIndicator();
        
        if (response.ok) {
            const data = await response.json();
            const aiResponse = data.response;
            
            // Add AI response to shared conversation history
            rilonoAiConversationHistory.push({
                role: 'assistant',
                content: aiResponse
            });
            
            // Keep only last 20 messages in history
            if (rilonoAiConversationHistory.length > 20) {
                rilonoAiConversationHistory = rilonoAiConversationHistory.slice(-20);
            }
            
            // Add to both chats
            addMessageToRilonoAiChat(aiResponse, false);
            addMessageToFloatingChat(aiResponse, false);
        } else {
            const errorData = await response.json();
            const errorMsg = errorData.detail || 'Failed to get response from Rilono AI';
            addMessageToRilonoAiChat(`Sorry, I encountered an error: ${errorMsg}. Please try again.`, false);
        }
    } catch (error) {
        removeRilonoAiTypingIndicator();
        console.error('Rilono AI chat error:', error);
        addMessageToRilonoAiChat('Sorry, I encountered an error. Please try again later.', false);
    }
}

function generateRilonoAiResponse(userMessage) {
    const message = userMessage.toLowerCase();
    
    if (message.includes('document') || message.includes('checklist') || message.includes('upload')) {
        return `Here are the key documents you need to upload for your US visa application:

📋 **Required Documents:**
• Passport (valid for at least 6 months)
• DS-160 Confirmation Page
• DS-160 Application
• US Visa Appointment Letter
• Visa Fee Receipt
• Photograph (2x2 Inches)
• Form I-20 (Signed)
• University Admission Letter
• Bank balance certificate
• Transcripts / mark sheets
• Degree certificates
• I-901 SEVIS fee payment confirmation

You can check your profile completion status in the Overview tab to see which documents you've already uploaded and which are still pending.`;
    } else if (message.includes('profile') || message.includes('status') || message.includes('complete')) {
        return `I can help you check your profile completion! Here's what you can do:

1. **Check Overview Tab**: Go to the Overview section to see your profile completion percentage and pending documents.

2. **Profile Information**: Make sure you've filled out:
   • Full Name
   • University
   • Phone Number
   • Profile Picture

3. **Documents**: Upload all required documents in the Documents tab.

Would you like me to help you with any specific document or profile field?`;
    } else if (message.includes('visa') || message.includes('application') || message.includes('process')) {
        return `I'm here to help with your visa application process! Here's a general overview:

🛂 **US Student Visa Process:**

1. **Get I-20**: Receive your I-20 form from your university
2. **Pay SEVIS Fee**: Pay the I-901 SEVIS fee and get confirmation
3. **Complete DS-160**: Fill out the DS-160 application form online
4. **Pay Visa Fee**: Pay the visa application fee
5. **Schedule Interview**: Book your visa appointment
6. **Prepare Documents**: Gather all required documents
7. **Attend Interview**: Go to your visa interview

For specific guidance on any step, feel free to ask! I can also help you track which documents you've uploaded and what's still pending.`;
    } else if (message.includes('help') || message.includes('assist')) {
        return `I'm Rilono AI, and I'm here to help you with:

✅ Document requirements and checklists
✅ Visa application guidance
✅ Profile completion tracking
✅ Answering questions about your uploaded documents
✅ General visa process information

You can ask me about:
• What documents you need
• Your profile completion status
• Visa application steps
• Document requirements
• Any other questions about your visa journey

What would you like to know?`;
    } else {
        return `I understand you're asking about "${userMessage}". 

I'm here to help with your visa documentation and application process. I can assist with:
• Document requirements and checklists
• Profile completion status
• Visa application guidance
• Questions about your uploaded documents

Could you be more specific about what you need help with? Or try one of the quick action buttons below!`;
    }
}

// Initialize Rilono AI Chat when tab is shown
function initializeRilonoAiChat() {
    const chatForms = getMainChatForms();
    chatForms.forEach((chatForm) => {
        // Remove existing listener to prevent duplicates
        chatForm.removeEventListener('submit', handleRilonoAiChatSubmit);
        chatForm.addEventListener('submit', handleRilonoAiChatSubmit);
    });
    // Sync messages from shared history
    syncMainChatFromHistory();
}

// Floating Chat Widget Functions
let floatingChatOpen = false;
// Note: floatingChatConversationHistory removed - using shared rilonoAiConversationHistory instead

function toggleFloatingChat() {
    const widget = document.getElementById('floatingAiChatWidget');
    const chatWindow = document.getElementById('floatingChatWindow');
    const chatToggle = document.getElementById('floatingChatToggle');
    const messagesContainer = document.getElementById('floatingChatMessages');
    
    // Toggle the state
    floatingChatOpen = !floatingChatOpen;
    
    // If closing, hide window and show toggle button
    if (!floatingChatOpen) {
        chatWindow.style.display = 'none';
        if (chatToggle) chatToggle.style.display = 'flex';
        return;
    }
    
    // Hide toggle button when chat is open
    if (chatToggle) chatToggle.style.display = 'none';
    
    if (!currentUser) {
        // Show login prompt
        document.getElementById('floatingChatLoginPrompt').style.display = 'flex';
        document.getElementById('floatingChatInputContainer').style.display = 'none';
        messagesContainer.innerHTML = '';
        chatWindow.style.display = 'flex';
        return;
    }
    
    if (floatingChatOpen) {
        chatWindow.style.display = 'flex';
        document.getElementById('floatingChatLoginPrompt').style.display = 'none';
        document.getElementById('floatingChatInputContainer').style.display = 'block';
        messagesContainer.style.display = 'flex';
        
        // Sync conversation from shared history
        syncFloatingChatFromHistory();
        
        // Ensure proper layout and scrolling
        setTimeout(() => {
            const messagesContainer = document.getElementById('floatingChatMessages');
            if (messagesContainer) {
                messagesContainer.style.display = 'flex';
                // Force a reflow to ensure scrolling works
                messagesContainer.offsetHeight;
                scrollFloatingChatToBottom();
            }
            document.getElementById('floatingChatInput')?.focus();
        }, 150);
    } else {
        chatWindow.style.display = 'none';
    }
}

// Sync floating chat UI from shared conversation history
function syncFloatingChatFromHistory() {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;
    
    // Clear existing messages
    messagesContainer.innerHTML = '';
    
    // Show welcome message if no conversation history
    if (rilonoAiConversationHistory.length === 0) {
        const welcomeDiv = document.createElement('div');
        welcomeDiv.className = 'chat-welcome-message';
        welcomeDiv.innerHTML = `
            <div class="chat-avatar">🤖</div>
            <div class="welcome-bubble">
                <p><strong>Hello! I'm Rilono AI</strong></p>
                <p>I'm here to help you with your F1 student visa process and documentation. How can I assist you today?</p>
            </div>
        `;
        messagesContainer.appendChild(welcomeDiv);
    } else {
        // Rebuild messages from shared history
        for (const msg of rilonoAiConversationHistory) {
            addMessageToFloatingChat(msg.content, msg.role === 'user');
        }
    }
    
    scrollFloatingChatToBottom();
}

// Sync main Rilono AI chat UI from shared conversation history
function syncMainChatFromHistory() {
    const messagesContainers = getMainChatContainers();
    if (messagesContainers.length === 0) return;

    messagesContainers.forEach((messagesContainer) => {
        messagesContainer.innerHTML = '';
    });

    if (rilonoAiConversationHistory.length === 0) {
        messagesContainers.forEach((messagesContainer) => {
            messagesContainer.innerHTML = getMainChatWelcomeMarkup();
        });
        return;
    }

    // Rebuild messages from shared history in all main chat panels
    for (const msg of rilonoAiConversationHistory) {
        addMessageToRilonoAiChat(msg.content, msg.role === 'user');
    }
}

function handleFloatingChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        document.getElementById('floatingChatForm').dispatchEvent(new Event('submit'));
    }
}

function autoResizeFloatingChatInput(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function scrollFloatingChatToBottom() {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;
    
    // Force immediate scroll first
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    // Then smooth scroll with requestAnimationFrame for better performance
    requestAnimationFrame(() => {
        messagesContainer.scrollTo({
            top: messagesContainer.scrollHeight,
            behavior: 'smooth'
        });
    });
}

function addMessageToFloatingChat(message, isUser = false) {
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (!messagesContainer) return;  // Guard: container might not exist
    
    // Remove welcome message if it exists (only when adding first user message)
    if (isUser) {
        const welcomeMsg = messagesContainer.querySelector('.chat-welcome-message');
        if (welcomeMsg) {
            welcomeMsg.remove();
        }
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${isUser ? 'user' : 'assistant'}`;
    
    if (!isUser) {
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = '🤖';
        messageDiv.appendChild(avatar);
    }
    
    const bubble = document.createElement('div');
    bubble.className = 'chat-message-bubble';
    
    if (isUser) {
        // User messages: plain text
        bubble.textContent = message;
    } else {
        // AI responses: parse markdown
        bubble.innerHTML = markdownToHtml(message);
    }
    messageDiv.appendChild(bubble);
    
    if (isUser) {
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = currentUser?.full_name?.charAt(0).toUpperCase() || currentUser?.username?.charAt(0).toUpperCase() || 'U';
        messageDiv.appendChild(avatar);
    }
    
    messagesContainer.appendChild(messageDiv);
    // Scroll to bottom with smooth behavior after DOM update
    scrollFloatingChatToBottom();
}

function showFloatingChatTyping() {
    const typingIndicator = document.getElementById('floatingChatTyping');
    typingIndicator.style.display = 'block';
    // Scroll to bottom to show typing indicator
    scrollFloatingChatToBottom();
}

function removeFloatingChatTyping() {
    const typingIndicator = document.getElementById('floatingChatTyping');
    typingIndicator.style.display = 'none';
}

async function handleFloatingChatSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('floatingChatInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    if (!authToken) {
        showMessage('Please login to chat with Rilono AI', 'error');
        toggleFloatingChat();
        return;
    }
    
    // Add user message to both chats
    addMessageToFloatingChat(message, true);
    addMessageToRilonoAiChat(message, true);
    
    // Add to shared conversation history
    rilonoAiConversationHistory.push({
        role: 'user',
        content: message
    });
    
    input.value = '';
    autoResizeFloatingChatInput(input);
    
    // Show typing indicator
    showFloatingChatTyping();
    
    try {
        // Call the AI chat API
        const response = await fetch(`${API_BASE}/api/ai-chat/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                message: message,
                conversation_history: rilonoAiConversationHistory.slice(-10)
            })
        });
        
        removeFloatingChatTyping();
        
        if (response.ok) {
            const data = await response.json();
            const aiResponse = data.response;
            
            // Add AI response to shared conversation history
            rilonoAiConversationHistory.push({
                role: 'assistant',
                content: aiResponse
            });
            
            // Keep only last 20 messages in history
            if (rilonoAiConversationHistory.length > 20) {
                rilonoAiConversationHistory = rilonoAiConversationHistory.slice(-20);
            }
            
            // Add to both chats
            addMessageToFloatingChat(aiResponse, false);
            addMessageToRilonoAiChat(aiResponse, false);
        } else {
            const errorData = await response.json();
            const errorMsg = errorData.detail || 'Failed to get response from Rilono AI';
            addMessageToFloatingChat(`Sorry, I encountered an error: ${errorMsg}. Please try again.`, false);
        }
    } catch (error) {
        removeFloatingChatTyping();
        console.error('Floating chat error:', error);
        addMessageToFloatingChat('Sorry, I encountered an error. Please try again later.', false);
    }
}

function updateFloatingChatVisibility() {
    const widget = document.getElementById('floatingAiChatWidget');
    const messagesContainer = document.getElementById('floatingChatMessages');
    if (currentUser) {
        widget.style.display = 'block';
        document.getElementById('floatingChatLoginPrompt').style.display = 'none';
        document.getElementById('floatingChatInputContainer').style.display = 'block';
        if (messagesContainer) {
            messagesContainer.style.display = 'flex';
        }
    } else {
        widget.style.display = 'block'; // Still show widget but with login prompt
        if (floatingChatOpen) {
            document.getElementById('floatingChatLoginPrompt').style.display = 'flex';
            document.getElementById('floatingChatInputContainer').style.display = 'none';
            if (messagesContainer) {
                messagesContainer.style.display = 'none';
            }
        }
    }
}

function handleGalleryKeyPress(e) {
    const modal = document.getElementById('imageGalleryModal');
    if (modal.style.display === 'none') return;
    
    switch(e.key) {
        case 'ArrowLeft':
            e.preventDefault();
            navigateGallery(-1);
            break;
        case 'ArrowRight':
            e.preventDefault();
            navigateGallery(1);
            break;
        case 'Escape':
            e.preventDefault();
            closeImageGallery();
            break;
    }
}
