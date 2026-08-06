document.getElementById('actDate').addEventListener('change', function () {
    const actDate = new Date(this.value);

    if (!isNaN(actDate.getTime())) {
      // 设置报名开始和结束时间的最大值为活动日期的前一天
      const startMin = new Date(actDate);
      const endMax = new Date(actDate);
      startMin.setDate(startMin.getDate() - 1);
      endMax.setDate(endMax.getDate() - 1);

      // 格式化日期为 datetime-local 格式的字符串 (YYYY-MM-DDTHH:MM)
      const formatDateTimeLocal = (date) => {
        const pad = (num) => (num < 10 ? '0' + num : num);
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
      };

      document.getElementById('actStart').max = formatDateTimeLocal(endMax);
      document.getElementById('actStop').max = formatDateTimeLocal(endMax);

      console.log('报名开始时间和结束时间最大值已设置为：', formatDateTimeLocal(endMax));
    }
  });