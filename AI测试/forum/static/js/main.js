// 自动关闭 alert
document.addEventListener('DOMContentLoaded', function () {
  const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
  alerts.forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 4000);
  });
});
