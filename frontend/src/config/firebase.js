import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";
import { getStorage } from "firebase/storage";

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIzaSyBW6HTppe51XDcCwX4HqhqU3FzfFG0PGtE",
  authDomain: "ai-research-assistant-3d978.firebaseapp.com",
  projectId: "ai-research-assistant-3d978",
  storageBucket: "ai-research-assistant-3d978.firebasestorage.app",
  messagingSenderId: "834085330184",
  appId: "1:834085330184:web:b05201c9a039da1e2aa0bd",
  measurementId: "G-M5VGCXMCYP"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();
export const storage = getStorage(app);

export default app;