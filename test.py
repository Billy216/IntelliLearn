import bcrypt

# 要哈希的密码
password = input('输入密码').encode('utf-8')

# 生成盐
salt = bcrypt.gensalt()

# 生成哈希值
hashed_password = bcrypt.hashpw(password, salt)

print("生成的哈希值:", hashed_password.decode('utf-8'))