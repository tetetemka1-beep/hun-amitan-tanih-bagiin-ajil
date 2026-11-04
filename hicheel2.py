# 1

# udur = input()
# if udur == "6" or udur == "7" :
#     print("amraltiin udur")
# else:
#     print("ajiliin udur")
# utga= int(input())
# dood_dun = 60
# deed_dun = 100
# if dood_dun <= utga and deed_dun >=utga :
#     print("tentssen")
# else:
#     print("unasan")


# r= input("name :")
# k="sain baina uu"

# print(k, r)

# a, b= map(int, input("too :"). split())
# print(a + b)

# a, b= map(int, input("ogogdol:" ) . split())
# print(a*b)

# a= int (input("radius :"))
# print(a*2)

# nas= int(input("odoogiin nas: "))
# print(nas+1)

# a= int(input("C:"))
# print(a*9/5+32)

# s= int(input("too:"))
# a=s//10
# b=s%10
# print(a + b)

# a= int(input("too:"))
# b= a//10
# d= a%10
# e= d*10
# print(e + b)

# a= int(input("minute:"))
# s=a//60n
# b=a%60
# print(s, b)

# too= int(input())
# if  0<too :
#     print("positive")
# elif 0>too:
#     print("negative")
# else :
#     print("zero")

# too= int(input())
# if too % 2 == 0 :
#     print("even")
# else:
#     print("odd")

# age= int(input())
# if age>= 18 :
#     print("adult")
# else:
#     print("child")

# a, b= map(int, input(). split())
# if a<b : 
#     print(b)
# else:
#     print(a)

# a, b, c= map(int, input(). split())
# if a < b < c :
#     print("yes")
# else:
#     print("no")

# score= int(input())
# dun= 0 < score > 100 
# if  score>=90:
#     print("A")
# elif score>=80:
#     print("B")
# elif score>=70:
#     print("C")
# elif score>=80:
#     print("D")
# else:
#     print("F")

# too= int(input())
# if too % 3 == 0 :
#     print("Yes")
# else :
#     print("No")

# a, b, c= map(int, input().split())
# baga=a
# if b < baga:
#     baga=b 
# if c < baga: 
#     baga=c
# print(baga)

# q=int(input())
# if 10 <= q <= 50 :
#     print("Yes")
# else:
#     print("No")

# age, ticket= input(). split()
# age=int(age)
# if age<= 12 or ticket == "yes":
#     print("ENTER")
# else:
#     print("no")

# onoo , irts = map(int, input() . split())
# if onoo >= 60 and irts >= 80 :
#     print("pass")
# else:
#     print("fail")

# password, nuuts_ug = input() . split()
# if password == nuuts_ug :
#     print("correct")
# else:
#     print("incorrect")

# a, b, c= map(int, input().split())

# irts, onoo = map(int, input() . split())
# if onoo >=90 and irts >= 90 :
#     print("Excellent")
# elif onoo >=70 and irts >= 80:
#     print("good")
# else:
#     print("Need Improvement")

# a= int(input())
# if a==1 :
#     print("Monday")
# elif a==2 :
#     print("Tuesday")
# elif a==3 :
#     print("Wednesday")
# elif a==4 :
#     print("Thursday")
# elif a==5 :
#     print("Friday")
# elif a==6 :
#     print("Saturday")
#     print("weekend")
# elif a==7 :
#     print("Sunday")
#     print("weekend")

# too= int(input())
# if too> 100 :
#     print("large")
# elif 0< too < 100 :
#     print("medium")
# elif too < 0 :
#     print("negative")
# if too > 100 and too%2 == 0 :
#     print("even")

# price, age = map(int, input().split())
# if age < 18:
#     price = price * 80 // 100
# elif age > 60:
#     price = price * 70 // 100
# print(price)

# a, b, c = map(int, input().split())
# if a + b > c and a + c > b and b + c > a:
#     print("YES")
# else:
#     print("NO")

# age, password, admin = input().split()
# age=int(age)
# password= int(password) 
# if age < 18 :
#     print("denied")
# elif password = 1234:
#     print("wrong password")
# elif admin == "yes":
#     print("admin access")
# else:
#     print("user access")

# balance, amount = map(int, input().split())

# if amount <= 0 or amount % 1000 :
#     print("Invalid amount")
# elif amount > balance:
#     print("Insufficient balance")
# else:
#     print("Remaining:", balance - amount)


# task1

# a, b, c = map(int, input().split())
# if a + b <= c or a + c <= b or b + c <= a:
#     print("NOT A TRIANGLE")
# elif a == b == c:
#     print("Equilateral")
# elif a == b or a == c or b == c:
#     print("Isosceles")
# else:
#     print("Scalene")


# task2

# age, day = input().split()
# age = int(age)
# if age < 12 or age > 60:
#     print(5000)
# elif day == "weekend":
#     print(12000)
# else:
#     print(10000)


# task3


# name, password, status = input().split()

# if name == "admin" and password == "1234":
#     if status == "blocked":
#         print("ACCOUNT BLOCKED")
#     else:
#         print("WELCOME")
# else:
#     print("LOGIN FAILED")

# task4

# x1, y1, x2, y2= map(int, input(). split())
# x, y= map(int, input(). split())
# if x1< x < x2 and y1< y < y2 :
#     print("inside")
# else:
#     print("outside")

# task5

# a1, b1, a2, b2= map(int, input(). split())
# if a1 <= b2 and a2 <= b1 :
#     print("YES")
# else:
#     print("NO")

# task6

# day, month, year= map(int, input(). split())
# if month < 1 or 12 < month or day < 1 :
#         print("INVALID")
# elif month== 2:
#     if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0) and day <= 29:
#         print("valid")
#     elif year % 400 != 0 or (year % 4 != 0 and year % 100 != 0) and day <= 28:
#         print("valid")
#     else:
#         print("invalid")
# elif month == 4 or month == 6 or month == 9 or month == 11 :
#         if day <= 30 :
#             print("VALID")
# elif month == 1 or month == 3 or month==5 or month== 7 or month == 8 or month == 10 or month == 12:
#     if day<=31:
#         print("VALID")
# else:
#     print("INVALID")

# task7

# r, c= map(int, input().split())
# if r < 1 or 8 < r or c < 1 or 8 < c :
#     print("invalid")
# elif (r +c) % 2 == 0: 
#     print("black")
# else :
#     print("white")

# task8

# a, b, c = map(int, input(). split ())
# if a >= 90 and b >= 95 and c==0 :
#     print("full")
# elif a >= 80 and b >= 90 and c <= 1:
#     print("half")
# else:
#     print("none")

# task9

# p1, p2 = input().split 5()
# if p1 == p2 :
#     print("draw")
# elif p1 == "rock" and p2 == "scissors" :
#     print("player1")
# elif p1 == "scissors" and p2 == "paper" :
#     print("player1")
# elif p1 == "paper" and p2 == "rock" :
#     print("player1")
# else: 
#     print("player2")


# task3.1

# a, b, c = map(int, input(). split())
# if a > b :
#     a, b = b, a
# if b > c :
#     b, c = c, b
# if a > b :
#     a, b = b, a
#     print(a, b, c)

# task3.2

# tsag1, minut1 = map(int, input("ehleh tsag:"). split())
# tsag2 , minut2 = map(int, input("duusah tsag:"). split())
# ehleh = tsag1 * 60 + minut1 
# duusah = tsag2 * 60 + minut2
# if duusah < ehleh :
#     duusah = duusah + 24 * 60
# zoruu = duusah-ehleh 
# print(zoruu//60 , zoruu % 60 )


# task3.3

# a, b, c = map(int, input() .split())

# if a + b <= c or a + c <= b or b + c <= a :
#     print("not a trangle")
# else:
#     if a > b :
#         a, b = b, a
#     if b > c :
#         b, c = c, b
#     if a > b :
#         a, b = b, a
# if a*a + b*b == c*c :
#     print("right")
# elif a*a + b*b > c*c :
#     print("acute")
# elif a*a + b*b < c*c :
#     print("obsute")


# task3.4

# a, b, c = map(int, input().split())

# if a == 0:
#     if b == 0:
#         if c == 0:
#             print("INF")
#         else:
#             print("NO ROOTS")
#     else:
#         print("ONE ROOT")
# else:
#     D = b * b - 4 * a * c

#     if D > 0:
#         print("TWO ROOTS")
#     elif D == 0:
#         print("ONE ROOT")
#     else:
#         print("NO ROOTS")


# task3.5

# day, month, year = map(int, input().split())

# if month == 2:
#     if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0):
#         days = 29
#     else:
#         days = 28
# elif month == 4 or month == 6 or month == 9 or month == 11:
#     days = 30
# else:
#     days = 31

# if day < days:
#     day = day + 1
# else:
#     day = 1
#     month = month + 1

#     if month > 12:
#         month = 1
#         year = year + 1

# print(day, month, year)

# task3.6

# x1, y1, x2, y2 = map(int, input().split())
# x3, y3, x4, y4 = map(int, input().split())

# if x2 < x3 or x4 < x1 or y2 < y3 or y4 < y1:
#     print("NO")
# else:
#     print("YES")




