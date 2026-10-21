LIST p=16f877a
    INCLUDE "p16f877a.inc"
    __CONFIG h'3F31'

num1    equ 0x25
num2    equ 0x26
result  equ 0x27
sayac1  equ 0x28
sayac2  equ 0x29
sayac3  equ 0x2A

    org 0x00
    goto start

start
    banksel TRISD
    clrf    TRISD        
    banksel PORTD        
    clrf    PORTD

    movlw   b'10111101'
    movwf   PORTD        
    call    delay        

    clrf    PORTD        
    call    delay        

    goto    start   


delay
    movlw   d'2'         
    movwf   sayac3
dongu3
    movlw   d'255'      
    movwf   sayac2
dongu2
    movlw   d'255'      
    movwf   sayac1
dongu1
    decfsz  sayac1, F   
    goto    dongu1      

    decfsz  sayac2, F    
    goto    dongu2      

    decfsz  sayac3, F   
    goto    dongu3      

    return               

    end