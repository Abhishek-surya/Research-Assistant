import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";
import { getStorage } from "firebase/storage";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyDLo966LU3zgfyHwwYxg7EbfXRi_9OQoW0",
  authDomain: "abhishek-rag-2026.firebaseapp.com",
  projectId: "abhishek-rag-2026",
  storageBucket: "abhishek-rag-2026.firebasestorage.app",
  messagingSenderId: "913577611628",
  appId: "1:913577611628:web:b0f7b693ec8520117aa349"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();
export const storage = getStorage(app);

export default app;