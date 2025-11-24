const API_BASE = '';
let currentUser = null;
let authToken = null;

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    initializeAddressAutocomplete();
    
    // Check authentication first
    await checkAuth();
    
    // Try to restore the last section the user was on
    const lastSection = sessionStorage.getItem('currentSection');
    
    if (lastSection) {
        // Restore the last section if user has access
        let sectionRestored = false;
        
        if (lastSection === 'home' && currentUser) {
            showHome();
            sectionRestored = true;
        } else if (lastSection === 'createItem' && currentUser) {
            showCreateItem();
            sectionRestored = true;
        } else if (lastSection === 'myListings' && currentUser) {
            showMyListings();
            sectionRestored = true;
        } else if (lastSection === 'messages' && currentUser) {
            showMessages();
            sectionRestored = true;
            } else if (lastSection === 'dashboard' && currentUser) {
                showDashboard();
                sectionRestored = true;
            } else if (lastSection === 'profile' && currentUser) {
                // Legacy support - redirect to dashboard
                showDashboard();
                sectionRestored = true;
        } else if (lastSection === 'login' && !currentUser) {
            showLogin();
            sectionRestored = true;
        } else if (lastSection === 'register' && !currentUser) {
            showRegister();
            sectionRestored = true;
        }
        
        // If we couldn't restore (user logged out/in, or invalid section), show default
        if (!sectionRestored) {
            if (currentUser) {
                showHome();
            } else {
                showLogin();
            }
        }
    } else {
        // No previous section, show appropriate default
        if (currentUser) {
            showHome();
        } else {
            showLogin();
        }
    }
    
    checkUnreadMessages();
    // Check for unread messages every 30 seconds
    setInterval(checkUnreadMessages, 30000);
});

function setupEventListeners() {
    document.getElementById('loginForm').addEventListener('submit', handleLogin);
    document.getElementById('registerForm').addEventListener('submit', handleRegister);
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
function showLogin() {
    hideAllSections();
    document.getElementById('loginSection').style.display = 'block';
    sessionStorage.setItem('currentSection', 'login');
}

function showRegister() {
    hideAllSections();
    document.getElementById('registerSection').style.display = 'block';
    sessionStorage.setItem('currentSection', 'register');
}

function showHome() {
    hideAllSections();
    document.getElementById('homeSection').style.display = 'block';
    loadItems();
    sessionStorage.setItem('currentSection', 'home');
}

function showCreateItem() {
    if (!currentUser) {
        showMessage('Please login to list an item', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('createItemSection').style.display = 'block';
    sessionStorage.setItem('currentSection', 'createItem');
    
    // Reset form if not editing
    if (!document.getElementById('editingItemId').value) {
        resetItemForm();
    }
}

function showMyListings() {
    if (!currentUser) {
        showMessage('Please login to view your listings', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('myListingsSection').style.display = 'block';
    loadMyItems();
    sessionStorage.setItem('currentSection', 'myListings');
}

function showMessages() {
    if (!currentUser) {
        showMessage('Please login to view messages', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('messagesSection').style.display = 'block';
    loadConversations();
    sessionStorage.setItem('currentSection', 'messages');
}

function showDashboard() {
    if (!currentUser) {
        showMessage('Please login to view dashboard', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('dashboardSection').style.display = 'block';
    loadProfile();
    loadDashboardStats();
    sessionStorage.setItem('currentSection', 'dashboard');
}

function hideAllSections() {
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
}

// Auth functions
async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;

    if (!username || !password) {
        showMessage('Please enter both username and password', 'error');
        return;
    }

    try {
        const formData = new URLSearchParams();
        formData.append('username', username);
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
            showHome();
        } else {
            let errorMessage = 'Login failed';
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
        username: getValue('registerUsername'),
        password: getValue('registerPassword'),
        full_name: getValue('registerFullName'),
        university: getValue('registerUniversity'),
        phone: getValue('registerPhone')
    };

    // Validate required fields
    if (!userData.email || !userData.username || !userData.password) {
        showMessage('Please fill in all required fields (Email, Username, Password)', 'error');
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
            showMessage('Registration successful! Please login.', 'success');
            document.getElementById('registerForm').reset();
            showLogin();
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
    showHome();
}

// Item functions
async function loadItems() {
    const search = document.getElementById('searchInput')?.value || '';
    const category = document.getElementById('categoryFilter')?.value || '';
    const minPrice = document.getElementById('minPrice')?.value || '';
    const maxPrice = document.getElementById('maxPrice')?.value || '';

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

    container.innerHTML = items.map(item => {
        // Get images - prefer new images array, fallback to image_url
        const images = item.images && item.images.length > 0 
            ? item.images.map(img => img.image_url)
            : (item.image_url ? [item.image_url] : []);
        
        const firstImage = images.length > 0 ? images[0] : null;
        const imageUrl = firstImage ? getImageUrl(firstImage) : null;
        const imageCount = images.length;
        
        return `
        <div class="item-card">
            <div class="item-image" style="position: relative;">
                ${imageUrl ? `<img src="${imageUrl}" alt="${item.title}" style="width: 100%; height: 100%; object-fit: cover;" onerror="this.parentElement.innerHTML='📦';">` : '📦'}
                ${imageCount > 1 ? `<div style="position: absolute; bottom: 0.5rem; right: 0.5rem; background: rgba(0,0,0,0.7); color: white; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.875rem;">${imageCount} photos</div>` : ''}
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
                    <div class="item-actions">
                        <button class="btn btn-primary" onclick="editItem(${item.id})">Edit</button>
                        <button class="btn btn-primary" onclick="markAsSold(${item.id})">Mark as Sold</button>
                        <button class="btn btn-danger" onclick="deleteItem(${item.id})">Delete</button>
                    </div>
                ` : !item.is_sold && (!currentUser || currentUser.id !== item.seller_id) ? `
                    <div class="item-actions">
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
    } catch (error) {
        console.error('Load dashboard stats error:', error);
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
            showHome();
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

