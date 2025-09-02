// RAGline API Test Client
class RAGlineClient {
    constructor() {
        this.token = null;
        this.baseUrl = 'http://localhost:8000';
        this.llmUrl = 'http://localhost:8001';
        this.eventSource = null;
    }

    setToken(token) {
        this.token = token;
    }

    getHeaders() {
        const headers = {
            'Content-Type': 'application/json',
        };
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        return headers;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const config = {
            headers: this.getHeaders(),
            ...options,
        };

        try {
            const response = await fetch(url, config);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    }

    // Auth methods
    async login(email, password, tenantId) {
        const data = await this.request('/v1/auth/login', {
            method: 'POST',
            body: JSON.stringify({
                email,
                password,
                tenant_id: tenantId,
            }),
        });
        this.setToken(data.access_token);
        return data;
    }

    // Product methods
    async createProduct(name, description, price) {
        return this.request('/v1/products/', {
            method: 'POST',
            body: JSON.stringify({
                name,
                description,
                price: parseInt(price),
                is_active: true,
            }),
        });
    }

    async listProducts(skip = 0, limit = 100, search = null) {
        let endpoint = `/v1/products/?skip=${skip}&limit=${limit}`;
        if (search) {
            endpoint += `&search=${encodeURIComponent(search)}`;
        }
        return this.request(endpoint);
    }

    // Order methods
    async createOrder(items, idempotencyKey = null) {
        const headers = this.getHeaders();
        if (idempotencyKey) {
            headers['Idempotency-Key'] = idempotencyKey;
        }

        return this.request('/v1/orders/', {
            method: 'POST',
            headers,
            body: JSON.stringify({ items }),
        });
    }

    async listOrders(skip = 0, limit = 100, status = null) {
        let endpoint = `/v1/orders/?skip=${skip}&limit=${limit}`;
        if (status) {
            endpoint += `&status=${status}`;
        }
        return this.request(endpoint);
    }

    async updateOrder(orderId, status) {
        return this.request(`/v1/orders/${orderId}`, {
            method: 'PUT',
            body: JSON.stringify({ status }),
        });
    }

    async cancelOrder(orderId) {
        return this.request(`/v1/orders/${orderId}`, {
            method: 'DELETE',
        });
    }

    // Health check
    async checkHealth() {
        return this.request('/health');
    }

    // SSE Events
    connectSSE() {
        if (this.eventSource) {
            this.eventSource.close();
        }

        const url = `${this.baseUrl}/v1/events/stream`;
        this.eventSource = new EventSource(url);
        
        this.eventSource.onopen = () => {
            this.logEvent('SSE connected');
        };

        this.eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.logEvent(`Event: ${data.event_type} - ${JSON.stringify(data, null, 2)}`);
            } catch (e) {
                this.logEvent(`Raw event: ${event.data}`);
            }
        };

        this.eventSource.onerror = (error) => {
            this.logEvent('SSE connection error', 'error');
        };
    }

    disconnectSSE() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
            this.logEvent('SSE disconnected');
        }
    }

    logEvent(message, type = 'info') {
        const eventsDiv = document.getElementById('eventsResult');
        if (eventsDiv) {
            const timestamp = new Date().toLocaleTimeString();
            eventsDiv.textContent += `[${timestamp}] ${message}\n`;
            eventsDiv.scrollTop = eventsDiv.scrollHeight;
        }
    }
}

// Global client instance
const client = new RAGlineClient();

// UI Helper Functions
function showResult(elementId, data, isError = false) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = JSON.stringify(data, null, 2);
        element.className = isError ? 'result error' : 'result success';
    }
}

// Auth functions
async function login() {
    const tenant = document.getElementById('loginTenant').value;
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    
    try {
        const data = await client.login(email, password, parseInt(tenant));
        document.getElementById('authStatus').textContent = 'Authenticated';
        document.getElementById('authStatus').className = 'status ready';
        console.log('Login successful:', data);
    } catch (error) {
        document.getElementById('authStatus').textContent = 'Auth failed';
        document.getElementById('authStatus').className = 'status error';
        console.error('Login failed:', error);
    }
}

// Product functions
async function createProduct() {
    const name = document.getElementById('productName').value;
    const description = document.getElementById('productDesc').value;
    const price = document.getElementById('productPrice').value;
    
    try {
        const data = await client.createProduct(name, description, price);
        showResult('productsResult', data);
        // Clear inputs
        document.getElementById('productName').value = '';
        document.getElementById('productDesc').value = '';
        document.getElementById('productPrice').value = '';
    } catch (error) {
        showResult('productsResult', { error: error.message }, true);
    }
}

async function listProducts() {
    const search = document.getElementById('productSearch').value;
    
    try {
        const data = await client.listProducts(0, 100, search || null);
        showResult('productsResult', data);
    } catch (error) {
        showResult('productsResult', { error: error.message }, true);
    }
}

// Order functions
async function createOrder() {
    const sku = document.getElementById('orderSku').value;
    const quantity = parseInt(document.getElementById('orderQty').value);
    
    try {
        const items = [{ sku, quantity }];
        const data = await client.createOrder(items, `test-${Date.now()}`);
        showResult('ordersResult', data);
        // Clear inputs
        document.getElementById('orderSku').value = '';
        document.getElementById('orderQty').value = '';
    } catch (error) {
        showResult('ordersResult', { error: error.message }, true);
    }
}

async function listOrders() {
    const status = document.getElementById('orderStatus').value || null;
    
    try {
        const data = await client.listOrders(0, 100, status);
        showResult('ordersResult', data);
    } catch (error) {
        showResult('ordersResult', { error: error.message }, true);
    }
}

// Event functions
function connectSSE() {
    client.connectSSE();
}

function disconnectSSE() {
    client.disconnectSSE();
}

// Health check
async function checkHealth() {
    try {
        const data = await client.checkHealth();
        showResult('healthResult', data);
    } catch (error) {
        showResult('healthResult', { error: error.message }, true);
    }
}