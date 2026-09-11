import axios from 'axios';

const authBaseURL = import.meta.env.VITE_AUTH_API_BASE_URL || '/api/auth';

export const authApi = axios.create({
    baseURL: authBaseURL,
});
