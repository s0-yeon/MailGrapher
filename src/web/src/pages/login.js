import '../main.scss';
import '../utils/security.js';
import '../scss/pages/login.scss';

document.addEventListener('DOMContentLoaded', function () {
  const loginCard = document.getElementById('loginCard');
  const registerCard = document.getElementById('registerCard');
  const showRegisterForm = document.getElementById('showRegisterForm');
  const showLoginForm = document.getElementById('showLoginForm');
  const togglePassword = document.getElementById('togglePassword');
  const passwordInput = document.getElementById('password');
  const eyeIcon = document.getElementById('eyeIcon');

  // Form switching
  showRegisterForm.addEventListener('click', function (e) {
    e.preventDefault();
    loginCard.classList.add('d-none');
    registerCard.classList.remove('d-none');
  });

  showLoginForm.addEventListener('click', function (e) {
    e.preventDefault();
    registerCard.classList.add('d-none');
    loginCard.classList.remove('d-none');
  });

  // Password toggle
  togglePassword.addEventListener('click', function () {
    const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
    passwordInput.setAttribute('type', type);
    eyeIcon.classList.toggle('fa-eye');
    eyeIcon.classList.toggle('fa-eye-slash');
  });

  // Form submissions (design only — no OAuth yet, just land on the home page)
  document.getElementById('loginForm').addEventListener('submit', function (e) {
    e.preventDefault();
    window.location.href = 'index.html';
  });

  document.getElementById('registerForm').addEventListener('submit', function (e) {
    e.preventDefault();
    window.location.href = 'index.html';
  });
});
