const API_BASE = '';
let currentUser = null;
let authToken = null;

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
    } else if (path === '/marketplace') {
        // Marketplace - check for search params
        if (queryParams.search || queryParams.category || queryParams.minPrice || queryParams.maxPrice) {
            showMarketplaceWithFilters(queryParams, skipURLUpdate);
        } else {
            showMarketplace(skipURLUpdate);
        }
    } else if (path === '/login') {
        showLogin(skipURLUpdate);
    } else if (path === '/register') {
        showRegister(skipURLUpdate);
    } else if (path === '/verify-email') {
        handleEmailVerification(skipURLUpdate);
    } else if (path === '/forgot-password') {
        showForgotPassword(skipURLUpdate);
    } else if (path === '/reset-password') {
        handleResetPasswordPage(skipURLUpdate);
    } else if (path === '/sell') {
        showCreateItem(skipURLUpdate);
    } else if (path === '/listings') {
        showMyListings(skipURLUpdate);
    } else if (path === '/messages') {
        showMessages(skipURLUpdate);
    } else if (path === '/dashboard') {
        showDashboard(skipURLUpdate);
    } else if (path === '/privacy') {
        showPrivacy(skipURLUpdate);
    } else if (path === '/terms') {
        showTerms(skipURLUpdate);
    } else if (path.startsWith('/item/')) {
        const itemId = path.split('/item/')[1];
        if (itemId) {
            showItemDetail(itemId, skipURLUpdate);
        } else {
            showMarketplace(skipURLUpdate);
        }
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

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    initializeAddressAutocomplete();
    
    // Set last updated dates for legal pages
    const today = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const privacyLastUpdated = document.getElementById('privacyLastUpdated');
    const termsLastUpdated = document.getElementById('termsLastUpdated');
    if (privacyLastUpdated) privacyLastUpdated.textContent = today;
    if (termsLastUpdated) termsLastUpdated.textContent = today;
    
    // Check authentication first
    await checkAuth();
    
    // Handle initial route (use replaceState for initial load)
    handleRoute(true);
    // Update URL once after initial route is handled
    const path = getPathFromURL();
    const queryParams = getQueryParams();
    if (path === '/marketplace' && (queryParams.search || queryParams.category || queryParams.minPrice || queryParams.maxPrice)) {
        const searchURL = buildSearchURL(queryParams.search, queryParams.category, queryParams.minPrice, queryParams.maxPrice);
        updateURL('/marketplace' + (searchURL !== '/' ? searchURL.replace('/', '?') : ''), true);
    } else {
        updateURL(path || '/', true);
    }
    
    checkUnreadMessages();
    // Check for unread messages every 30 seconds
    setInterval(checkUnreadMessages, 30000);
});

function setupEventListeners() {
    document.getElementById('loginForm').addEventListener('submit', handleLogin);
    document.getElementById('registerForm').addEventListener('submit', handleRegister);
    document.getElementById('forgotPasswordForm').addEventListener('submit', handleForgotPassword);
    document.getElementById('resetPasswordForm').addEventListener('submit', handleResetPassword);
    document.getElementById('createItemForm').addEventListener('submit', handleCreateItem);
    document.getElementById('profileForm').addEventListener('submit', handleUpdateProfile);
    document.getElementById('searchInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadItems();
    });
    
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
        document.getElementById('createLink').style.display = 'block';
        document.getElementById('userMenu').style.display = 'block';
        
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
        checkUnreadMessages();
        // Only load profile data if we're on the dashboard section
        const currentSection = sessionStorage.getItem('currentSection');
        if (currentSection === 'dashboard' || currentSection === 'profile') {
            loadProfile();
            loadDashboardStats();
        }
    } else {
        document.getElementById('loginLink').style.display = 'block';
        document.getElementById('registerLink').style.display = 'block';
        document.getElementById('createLink').style.display = 'none';
        document.getElementById('userMenu').style.display = 'none';
        
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

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const userMenu = document.getElementById('userMenu');
    const dropdown = document.getElementById('userMenuDropdown');
    if (userMenu && dropdown && !userMenu.contains(e.target)) {
        dropdown.style.display = 'none';
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
    const heroSellBtn = document.getElementById('heroSellBtn');
    const heroRegisterBtn = document.getElementById('heroRegisterBtn');
    const ctaRegisterBtn = document.getElementById('ctaRegisterBtn');
    
    if (currentUser) {
        if (heroSellBtn) heroSellBtn.style.display = 'inline-block';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'none';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'none';
    } else {
        if (heroSellBtn) heroSellBtn.style.display = 'none';
        if (heroRegisterBtn) heroRegisterBtn.style.display = 'inline-block';
        if (ctaRegisterBtn) ctaRegisterBtn.style.display = 'inline-block';
    }
    
    if (!skipURLUpdate) {
        updateURL('/', false); // Use pushState for navigation
    }
}

function showLogin(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('loginSection').style.display = 'block';
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
    hideAllSections();
    document.getElementById('marketplaceSection').style.display = 'block';
    // Clear search filters
    document.getElementById('searchInput').value = '';
    document.getElementById('categoryFilter').value = '';
    document.getElementById('minPrice').value = '';
    document.getElementById('maxPrice').value = '';
    loadItems(skipURLUpdate);
    if (!skipURLUpdate) {
        updateURL('/marketplace', false); // Use pushState for navigation
    }
}

function showMarketplaceWithFilters(params, skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('marketplaceSection').style.display = 'block';
    // Set search filters from URL
    if (document.getElementById('searchInput')) document.getElementById('searchInput').value = params.search || '';
    if (document.getElementById('categoryFilter')) document.getElementById('categoryFilter').value = params.category || '';
    if (document.getElementById('minPrice')) document.getElementById('minPrice').value = params.minPrice || '';
    if (document.getElementById('maxPrice')) document.getElementById('maxPrice').value = params.maxPrice || '';
    loadItems(skipURLUpdate);
    // Don't update URL if we're handling a route (skipURLUpdate = true)
    // This prevents overwriting the URL when back/forward is used
}

function showCreateItem(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to list an item', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('createItemSection').style.display = 'block';
    if (!skipURLUpdate) {
        updateURL('/sell', false); // Use pushState for navigation
    }
    
    // Reset form if not editing
    if (!document.getElementById('editingItemId').value) {
        resetItemForm();
    }
}

function showMyListings(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to view your listings', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('myListingsSection').style.display = 'block';
    loadMyItems();
    if (!skipURLUpdate) {
        updateURL('/listings', false); // Use pushState for navigation
    }
}

function showMessages(skipURLUpdate = false) {
    if (!currentUser) {
        showMessage('Please login to view messages', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('messagesSection').style.display = 'block';
    loadConversations();
    if (!skipURLUpdate) {
        updateURL('/messages', false); // Use pushState for navigation
    }
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

function showTerms(skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('termsSection').style.display = 'block';
    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (!skipURLUpdate) {
        updateURL('/terms', false);
    }
}

async function showItemDetail(itemId, skipURLUpdate = false) {
    hideAllSections();
    document.getElementById('marketplaceSection').style.display = 'block';
    if (!skipURLUpdate) {
        updateURL(`/item/${itemId}`, false); // Use pushState for navigation
    }
    
    // Load and highlight the specific item
    try {
        const response = await fetch(`${API_BASE}/api/items/${itemId}`);
        if (response.ok) {
            const item = await response.json();
            // Scroll to item if it's in the current view, or load items and scroll
            loadItems(skipURLUpdate);
            setTimeout(() => {
                const itemCard = document.querySelector(`[data-item-id="${itemId}"]`);
                if (itemCard) {
                    itemCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    itemCard.style.border = '3px solid var(--primary-color)';
                    itemCard.style.boxShadow = '0 0 20px rgba(99, 102, 241, 0.5)';
                    setTimeout(() => {
                        itemCard.style.border = '';
                        itemCard.style.boxShadow = '';
                    }, 3000);
                }
            }, 500);
        } else {
            showMessage('Item not found', 'error');
            showMarketplace();
        }
    } catch (error) {
        console.error('Error loading item:', error);
        showMessage('Failed to load item', 'error');
        showMarketplace();
    }
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

    try {
        const formData = new URLSearchParams();
        formData.append('username', email);  // OAuth2PasswordRequestForm expects 'username' field, but we use it for email
        formData.append('password', password);

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
            showMarketplace();
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
    const search = document.getElementById('searchInput')?.value || '';
    const category = document.getElementById('categoryFilter')?.value || '';
    const minPrice = document.getElementById('minPrice')?.value || '';
    const maxPrice = document.getElementById('maxPrice')?.value || '';

    // Update URL with current search filters (only if not handling back/forward)
    if (!skipURLUpdate) {
        const searchURL = buildSearchURL(search.trim(), category, minPrice, maxPrice);
        updateURL('/marketplace' + (searchURL ? '?' + searchURL : ''), false); // Use pushState when user actively searches
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
    
    showMessages();
    // Small delay to ensure messages section is loaded
    setTimeout(() => {
        openConversation(itemId, sellerId, '', '');
        // Load item details to get seller info
        fetch(`${API_BASE}/api/items/${itemId}`)
            .then(res => res.json())
            .then(item => {
                if (currentConversation) {
                    currentConversation.itemTitle = item.title;
                    currentConversation.otherUsername = item.seller.username;
                    // Update header with seller details
                    const sellerName = item.seller.full_name || item.seller.username;
                    const sellerUniversity = item.seller.university || '';
                    document.getElementById('chatHeaderInfo').innerHTML = `
                        <div>
                            <strong>${escapeHtml(sellerName)}</strong>
                            ${sellerUniversity ? `<div style="font-size: 0.875rem; color: var(--text-secondary);">${escapeHtml(sellerUniversity)}</div>` : ''}
                            <div style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.25rem;">${escapeHtml(item.title)}</div>
                        </div>
                    `;
                }
            })
            .catch(err => {
                console.error('Failed to load item:', err);
            });
    }, 100);
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
}

async function loadDashboardStats() {
    if (!authToken) return;
    
    try {
        // Load user's items to count active and sold
        const itemsResponse = await fetch(`${API_BASE}/api/items/my/listings`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (itemsResponse.ok) {
            const items = await itemsResponse.json();
            const activeCount = items.filter(item => !item.is_sold).length;
            const soldCount = items.filter(item => item.is_sold).length;
            
            document.getElementById('activeListingsCount').textContent = activeCount;
            document.getElementById('soldItemsCount').textContent = soldCount;
        }
        
        // Load unread messages count
        const messagesResponse = await fetch(`${API_BASE}/api/messages/unread-count`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (messagesResponse.ok) {
            const data = await messagesResponse.json();
            document.getElementById('unreadCount').textContent = data.unread_count || 0;
            
            // Get total conversations count
            const convResponse = await fetch(`${API_BASE}/api/messages/conversations`, {
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });
            if (convResponse.ok) {
                const conversations = await convResponse.json();
                document.getElementById('messagesCount').textContent = conversations.length || 0;
            }
        }
        
        // Load profile completion and pending documents
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
    } catch (error) {
        console.error('Load profile completion error:', error);
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
        university: getValue('profileUniversity'),
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

async function handleDeleteAccount() {
    if (!authToken) {
        showMessage('Please login to delete your account', 'error');
        return;
    }
    
    // Double confirmation
    const confirmText = 'DELETE';
    const userInput = prompt(`This action cannot be undone. All your data including items, messages, and profile will be permanently deleted.\n\nType "${confirmText}" to confirm account deletion:`);
    
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
    
    // Save preferences to localStorage
    const preferences = {
        country: country,
        intake: intake,
        year: year,
        savedAt: new Date().toISOString()
    };
    
    localStorage.setItem('documentationPreferences', JSON.stringify(preferences));
    
    showMessage(`Preferences saved: ${intake} ${year}`, 'success');
    
    // TODO: In the future, this will send data to the backend API
    // For now, we're just storing it locally
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
        if (documentType) formData.append('document_type', documentType);
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
            showMessage('Document encrypted and uploaded successfully!', 'success');
            document.getElementById('documentUploadForm').reset();
            await loadMyDocuments();
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
            
            html += `
                <div style="border: 1px solid #c3e6cb; border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem; background: #d4edda;">
                    <div style="display: flex; align-items: start; gap: 0.75rem;">
                        <div style="color: #28a745; font-size: 1.25rem; font-weight: bold; flex-shrink: 0;">✓</div>
                        <div style="flex: 1;">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
                                <div style="flex: 1;">
                                    <div style="font-weight: 600; margin-bottom: 0.25rem; color: #155724;">
                                        ${escapeHtml(docTypeLabel)}
                                    </div>
                                    <div style="font-size: 0.875rem; color: var(--text-secondary);">
                                        ${escapeHtml(doc.original_filename)} • ${fileSizeMB} MB • ${uploadDate}
                                        ${isEncrypted ? ' • <span style="color: #28a745;">🔒 Encrypted</span>' : ''}
                                    </div>
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
                <div style="border: 1px solid #f5c6cb; border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem; background: #f8d7da;">
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
            
            return `
                <div style="border: 1px solid var(--border-color); border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem; background: var(--bg-color);">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
                        <div style="flex: 1;">
                            <div style="font-weight: 600; margin-bottom: 0.25rem;">
                                ${escapeHtml(doc.original_filename)}
                                ${isEncrypted ? '<span style="font-size: 0.75rem; color: #28a745; margin-left: 0.5rem;">🔒 Encrypted</span>' : ''}
                            </div>
                            <div style="font-size: 0.875rem; color: var(--text-secondary);">
                                ${doc.document_type ? `<span style="text-transform: capitalize;">${escapeHtml(doc.document_type)}</span> • ` : ''}
                                ${fileSizeMB} MB • ${uploadDate}
                            </div>
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
function handleRilonoAiChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        document.getElementById('rilonoAiChatForm').dispatchEvent(new Event('submit'));
    }
}

function autoResizeRilonoAiInput(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function sendQuickMessage(message) {
    const input = document.getElementById('rilonoAiChatInput');
    input.value = message;
    autoResizeRilonoAiInput(input);
    document.getElementById('rilonoAiChatForm').dispatchEvent(new Event('submit'));
}

function addMessageToRilonoAiChat(message, isUser = false) {
    const messagesContainer = document.getElementById('rilonoAiChatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = isUser ? 'user-message' : 'ai-message';
    
    if (isUser) {
        messageDiv.style.alignSelf = 'flex-end';
        messageDiv.style.maxWidth = '75%';
        messageDiv.innerHTML = `
            <div style="background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%); color: white; padding: 0.875rem 1.25rem; border-radius: 1rem; box-shadow: var(--shadow); border-top-right-radius: 0.25rem;">
                <p style="margin: 0; line-height: 1.6;">${escapeHtml(message)}</p>
            </div>
        `;
    } else {
        messageDiv.style.alignSelf = 'flex-start';
        messageDiv.style.maxWidth = '75%';
        messageDiv.innerHTML = `
            <div style="display: flex; gap: 0.75rem; align-items: start;">
                <div style="width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%); display: flex; align-items: center; justify-content: center; font-size: 1.25rem; flex-shrink: 0;">🤖</div>
                <div style="background: white; padding: 1rem; border-radius: 1rem; box-shadow: var(--shadow); border-top-left-radius: 0.25rem;">
                    <p style="margin: 0; color: var(--text-primary); line-height: 1.6; white-space: pre-wrap;">${escapeHtml(message)}</p>
                </div>
            </div>
        `;
    }
    
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    // Add animation
    messageDiv.style.opacity = '0';
    messageDiv.style.transform = 'translateY(10px)';
    setTimeout(() => {
        messageDiv.style.transition = 'all 0.3s ease';
        messageDiv.style.opacity = '1';
        messageDiv.style.transform = 'translateY(0)';
    }, 10);
}

function showRilonoAiTypingIndicator() {
    const messagesContainer = document.getElementById('rilonoAiChatMessages');
    const typingDiv = document.createElement('div');
    typingDiv.id = 'rilonoAiTypingIndicator';
    typingDiv.className = 'ai-message';
    typingDiv.style.alignSelf = 'flex-start';
    typingDiv.style.maxWidth = '75%';
    typingDiv.innerHTML = `
        <div style="display: flex; gap: 0.75rem; align-items: start;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%); display: flex; align-items: center; justify-content: center; font-size: 1.25rem; flex-shrink: 0;">🤖</div>
            <div style="background: white; padding: 1rem; border-radius: 1rem; box-shadow: var(--shadow); border-top-left-radius: 0.25rem;">
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <div style="width: 8px; height: 8px; border-radius: 50%; background: var(--text-secondary); animation: typingDot 1.4s infinite;"></div>
                    <div style="width: 8px; height: 8px; border-radius: 50%; background: var(--text-secondary); animation: typingDot 1.4s infinite; animation-delay: 0.2s;"></div>
                    <div style="width: 8px; height: 8px; border-radius: 50%; background: var(--text-secondary); animation: typingDot 1.4s infinite; animation-delay: 0.4s;"></div>
                </div>
            </div>
        </div>
    `;
    messagesContainer.appendChild(typingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeRilonoAiTypingIndicator() {
    const typingIndicator = document.getElementById('rilonoAiTypingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

async function handleRilonoAiChatSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('rilonoAiChatInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    // Add user message
    addMessageToRilonoAiChat(message, true);
    input.value = '';
    autoResizeRilonoAiInput(input);
    
    // Show typing indicator
    showRilonoAiTypingIndicator();
    
    // Simulate AI response (replace with actual API call later)
    setTimeout(() => {
        removeRilonoAiTypingIndicator();
        
        // Generate response based on message
        let response = generateRilonoAiResponse(message);
        addMessageToRilonoAiChat(response, false);
    }, 1000 + Math.random() * 1000); // Random delay between 1-2 seconds
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
    const chatForm = document.getElementById('rilonoAiChatForm');
    if (chatForm) {
        chatForm.addEventListener('submit', handleRilonoAiChatSubmit);
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

