const API_BASE = '';
let currentUser = null;
let authToken = null;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    setupEventListeners();
    loadItems();
    initializeAddressAutocomplete();
});

function setupEventListeners() {
    document.getElementById('loginForm').addEventListener('submit', handleLogin);
    document.getElementById('registerForm').addEventListener('submit', handleRegister);
    document.getElementById('createItemForm').addEventListener('submit', handleCreateItem);
    document.getElementById('searchInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadItems();
    });
    
    // Image preview for multiple file upload
    const imageFileInput = document.getElementById('itemImageFiles');
    if (imageFileInput) {
        imageFileInput.addEventListener('change', handleMultipleImagePreview);
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
            } else {
                localStorage.removeItem('authToken');
                authToken = null;
            }
        } catch (error) {
            console.error('Auth check failed:', error);
            localStorage.removeItem('authToken');
            authToken = null;
        }
    }
}

function updateUIForAuth() {
    if (currentUser) {
        document.getElementById('loginLink').style.display = 'none';
        document.getElementById('registerLink').style.display = 'none';
        document.getElementById('logoutLink').style.display = 'block';
        document.getElementById('createLink').style.display = 'block';
        document.getElementById('myListingsLink').style.display = 'block';
        document.getElementById('userInfo').style.display = 'block';
        document.getElementById('userInfo').textContent = `👤 ${currentUser.username}`;
    } else {
        document.getElementById('loginLink').style.display = 'block';
        document.getElementById('registerLink').style.display = 'block';
        document.getElementById('logoutLink').style.display = 'none';
        document.getElementById('createLink').style.display = 'none';
        document.getElementById('myListingsLink').style.display = 'none';
        document.getElementById('userInfo').style.display = 'none';
    }
}

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
}

function showRegister() {
    hideAllSections();
    document.getElementById('registerSection').style.display = 'block';
}

function showHome() {
    hideAllSections();
    document.getElementById('homeSection').style.display = 'block';
    loadItems();
}

function showCreateItem() {
    if (!currentUser) {
        showMessage('Please login to list an item', 'error');
        showLogin();
        return;
    }
    hideAllSections();
    document.getElementById('createItemSection').style.display = 'block';
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
                <div class="item-price">$${item.price.toFixed(2)}</div>
                ${item.category ? `<span class="item-category">${escapeHtml(item.category)}</span>` : ''}
                ${item.description ? `<div class="item-description">${escapeHtml(item.description)}</div>` : ''}
                ${item.address ? `<div class="item-location" style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.5rem;">📍 ${escapeHtml(item.address)}</div>` : ''}
                <div class="item-seller">Seller: ${escapeHtml(item.seller.username)}</div>
                ${showActions && !item.is_sold ? `
                    <div class="item-actions">
                        <button class="btn btn-primary" onclick="markAsSold(${item.id})">Mark as Sold</button>
                        <button class="btn btn-danger" onclick="deleteItem(${item.id})">Delete</button>
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

    if (!title || isNaN(price) || price < 0) {
        showMessage('Please fill in title and a valid price', 'error');
        return;
    }

    // Collect all image URLs
    let imageUrls = [];
    
    // Get files to upload
    const filesToUpload = selectedImages.filter(img => img.type === 'file').map(img => img.file);
    
    // Upload files if any
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

    if (!address) {
        showMessage('Please enter a pickup location', 'error');
        return;
    }

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
        const response = await fetch(`${API_BASE}/api/items/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(itemData)
        });

        const data = await response.json();

        if (response.ok) {
            showMessage('Item listed successfully!', 'success');
            document.getElementById('createItemForm').reset();
            document.getElementById('imagePreviews').innerHTML = '';
            document.getElementById('imagePreviews').style.display = 'none';
            document.getElementById('addressDetails').style.display = 'none';
            selectedImages = [];
            showHome();
            loadItems();
        } else {
            let errorMessage = 'Failed to create item';
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
        console.error('Create item error:', error);
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

