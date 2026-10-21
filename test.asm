LIST p=16f877a
    INCLUDE "p16f877a.inc"
    __CONFIG h'3F31'

num1    equ 0x25
num2    equ 0x26
result  equ 0x27

    org 0x00
    goto start

start
    banksel TRISD        
    clrf    TRISD        
    
    banksel PORTD        
    clrf    num1
    clrf    num2
    clrf    result
    clrf    PORTD
    
    movlw   b'11111010'  
    movwf   num1

    movlw   b'00000110'  
    movwf   num2        
    
    movf    num1, W      
    addwf   num2, W     
    movwf   result      

test
    btfss   STATUS, Z   
    goto    case1       
    goto    case2       

case1
    movf    result, W
    movwf   PORTD
    goto    finish

case2
    movlw   b'10111101'
    movwf   PORTD
    goto    finish

finish
    goto    finish    

    end